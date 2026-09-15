import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Every service image runs its process directly, with no `uv` in the way.
 *
 * `uv run` synchronises the environment before it execs. On Fly on 2026-08-30 a
 * machine spent two minutes on "Building koras-audit ... Built koras-database"
 * for eleven workspace packages *after* `Preparing to run` and before the
 * server process existed -- longer than the deploy pipeline's health-check
 * budget, so a service was reported as one that never became healthy.
 *
 * What triggered that resync was never established: the same image, built and
 * run locally from both the old and new Dockerfile, rebuilt nothing either way.
 * So this does not assert a reproduced trigger. It asserts that the mechanism
 * is absent -- with no `uv` at runtime, nothing in the container can rebuild
 * anything, whatever the trigger would have been.
 *
 * It also keeps the process at PID 1, which is what receives Fly's signals on
 * shutdown rather than a `uv` parent that has to forward them.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')

const IMAGES = [
  ['_shared', 'api'],
  ['_shared', 'worker'],
  ['_shared', 'scheduler'],
  ['product', 'ai-gateway'],
] as const

function dockerfile(layer: string, service: string): string {
  // A Dockerfile that gates a layer on a capability is a template; the
  // worker's is, since the reporting capability copies the API's catalogue
  // into its image. Read as text either way: what is asserted below is
  // outside any conditional block.
  const plain = join(PROFILES, layer, 'template', 'services', service, 'Dockerfile')
  const path = existsSync(plain) ? plain : `${plain}.hbs`
  expect(existsSync(path), `${layer}/${service} has no Dockerfile`).toBe(true)
  return readFileSync(path, 'utf8')
}

describe.each(IMAGES)('%s/%s image', (layer, service) => {
  const source = dockerfile(layer, service)

  it('does not invoke uv at runtime', () => {
    const cmd = source.split('\n').find((line) => line.startsWith('CMD '))
    expect(cmd, 'no CMD found').toBeDefined()
    expect(cmd).not.toContain('"uv"')
  })

  /**
   * The first sync runs before any source is copied, so it leaves every local
   * member installed from a manifest with nothing behind it. Without the
   * second, the venv in the image is incomplete and something has to finish
   * the job later -- which is the runtime rebuild this is all about.
   */
  it('syncs again after copying the source, so the venv in the image is complete', () => {
    const syncs = source.match(/uv sync --no-dev/g) ?? []
    expect(syncs.length).toBe(2)

    const sourceCopy = source.indexOf(`COPY services/${service}/koras_`)
    expect(sourceCopy, 'no source COPY found').toBeGreaterThan(-1)
    expect(source.lastIndexOf('uv sync --no-dev')).toBeGreaterThan(sourceCopy)
  })

  it('keeps the venv on PATH, which is what makes the bare command resolve', () => {
    expect(source).toContain('ENV PATH="/app/.venv/bin:$PATH"')
  })
})
