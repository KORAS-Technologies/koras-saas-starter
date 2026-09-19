import { describe, it, expect, beforeAll } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * A generated project compiles.
 *
 * Every other test here reads the files the generator wrote. None of them ever
 * built the result, and the gap was not theoretical: the control-plane profile
 * did not typecheck as generated for as long as anyone had been generating it.
 * The auth package imported a permissions package that was a two-line stub, its
 * manifest declared neither jose nor the workspace dependency, and the admin
 * application imported an api-client it never listed. Three defects, all
 * invisible to a test that reads text.
 *
 * This is slow -- install and build, a couple of minutes -- so it is one test
 * and it runs last. Slow and true beats fast and vacuous: the fast version was
 * 393 passing tests over a project that could not start.
 *
 * **Both profiles, since 2026-09-19, and the reason is the same gap one step
 * further on.** This built the control-plane profile alone for as long as it
 * had existed, which meant the profile that receives almost every feature was
 * the one never compiled locally. The settings framework found it the hard way:
 * `packages/api-client` and `packages/ui` each declared an `EffectiveSettings`,
 * structurally different and identically named, and `apps/web` passed one where
 * the other was expected. Every package typechecked on its own, all 1873 tests
 * here passed, and the generated product's build failed in CI.
 *
 * A duplicated type is invisible until something imports both. So is a missing
 * dependency, and so is an import that resolves in the template tree and not in
 * a merged one. Only a build sees them, and a build of one profile only sees
 * them in one profile.
 */

const PNPM = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
// Windows refuses to spawn a .cmd without a shell (EINVAL). The arguments
// here are all literals, so there is nothing for a shell to reinterpret.
const SHELL = process.platform === 'win32'
const REPO = join(__dirname, '..', '..', '..')

function buildsFor(profile: 'control-plane' | 'product', name: string) {
  describe(`a generated ${profile} project builds`, () => {
    let out: string
    let project: string
    let generated = false

    beforeAll(() => {
      out = mkdtempSync(join(tmpdir(), `koras-build-${profile}-`))
      project = join(out, name)
      execFileSync(
        PNPM,
        ['create-koras-app', name, '--profile', profile, '--no-interactive', '--output-dir', out],
        { cwd: REPO, timeout: 300_000, stdio: 'pipe', shell: SHELL },
      )
      generated = existsSync(join(project, 'package.json'))
    }, 300_000)

    it('installs and builds every workspace package and application', () => {
      expect(generated).toBe(true)
      execFileSync(PNPM, ['install', '--no-frozen-lockfile'], {
        cwd: project,
        timeout: 900_000,
        stdio: 'pipe',
        shell: SHELL,
      })
      // turbo, so packages build before the applications that import them.
      const result = execFileSync(PNPM, ['turbo', 'run', 'build'], {
        cwd: project,
        timeout: 1_200_000,
        encoding: 'utf8',
        shell: SHELL,
      })
      expect(result).toMatch(/Tasks:\s+(\d+) successful, \1 total/)
    }, 2_400_000)

    it('runs the tests it ships with', () => {
      // The auth package carries 39 of them. A generated project that cannot run
      // its own tests has shipped them as decoration.
      const result = execFileSync(PNPM, ['--filter', `@${name}/auth`, 'test'], {
        cwd: project,
        timeout: 600_000,
        encoding: 'utf8',
        shell: SHELL,
      })
      expect(result).toMatch(/fail 0/)
      expect(result).not.toMatch(/pass 0/)

      rmSync(out, { recursive: true, force: true })
    }, 900_000)
  })
}

buildsFor('control-plane', 'buildcheck')
buildsFor('product', 'buildcheckproduct')
