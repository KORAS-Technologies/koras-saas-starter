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
 */

const PNPM = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
// Windows refuses to spawn a .cmd without a shell (EINVAL). The arguments
// here are all literals, so there is nothing for a shell to reinterpret.
const SHELL = process.platform === 'win32'
const REPO = join(__dirname, '..', '..', '..')

describe('a generated project builds', () => {
  let out: string
  let project: string
  let generated = false

  beforeAll(() => {
    out = mkdtempSync(join(tmpdir(), 'koras-build-'))
    project = join(out, 'buildcheck')
    execFileSync(
      PNPM,
      ['create-koras-app', 'buildcheck', '--profile', 'control-plane', '--no-interactive', '--output-dir', out],
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
    const result = execFileSync(PNPM, ['--filter', '@buildcheck/auth', 'test'], {
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
