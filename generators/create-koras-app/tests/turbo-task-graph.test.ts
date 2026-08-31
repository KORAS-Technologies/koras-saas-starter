import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Two tasks that write the same directory must be ordered.
 *
 * `packages/auth` builds with `tsc` into `dist/` and tests with
 * `tsc && node --test dist/*.test.js`. Both write `dist/`. Turbo runs them
 * concurrently unless something says not to, and `dependsOn: ["^build"]` does
 * not: it orders a package's test after its *dependencies* build and says
 * nothing about its own.
 *
 * What that produced, on koras-e2e-shop's CI on 2026-08-31:
 *
 *     :23.474  auth:build   > tsc
 *     :23.970  auth:test    > tsc && node --test dist/*.test.js
 *     :23.983  SyntaxError: The requested module './index.js' does not
 *              provide an export named 'jwksUrl'
 *
 * from a file that exports `jwksUrl` on line 100. Node had loaded a
 * `dist/index.js` that the other `tsc` was still writing.
 *
 * The run before was green, and so was every local run. Adding one package to
 * the workspace was enough to move the two into the same half-second — which is
 * the whole difficulty with a race: it passes far more often than it fails, and
 * when it fails it accuses the wrong file.
 *
 * Asserted here rather than left to the build test, because the build test would
 * have to lose the race to notice, and mostly it will not.
 */

const TURBO = join(__dirname, '..', '..', '..', 'profiles', '_shared', 'template', 'turbo.json')

/** turbo.json is JSONC — the file carries comments, and turbo reads them. */
function readTurboConfig(): {
  tasks: Record<string, { dependsOn?: string[]; outputs?: string[] }>
} {
  const source = readFileSync(TURBO, 'utf8')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
  return JSON.parse(source)
}

describe('the generated turbo task graph', () => {
  const config = readTurboConfig()

  it('runs a package’s tests after that package has built', () => {
    expect(
      config.tasks.test?.dependsOn,
      'test must depend on `build`, not only `^build`: a package whose test script ' +
        'reads its own dist races its own build without it',
    ).toContain('build')
  })

  it('still builds dependencies first', () => {
    expect(config.tasks.test?.dependsOn).toContain('^build')
    expect(config.tasks.build?.dependsOn).toContain('^build')
  })

  /**
   * The guard on the guard. If `build` ever stopped declaring `dist/**` as an
   * output, the ordering above would still read correctly while turbo stopped
   * treating the directory as something a task owns.
   */
  it('still declares the directories a build owns', () => {
    const outputs = config.tasks.build?.outputs ?? []
    expect(outputs).toContain('dist/**')
    expect(outputs).toContain('.next/**')
  })
})
