import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { templatePath } from './template-path.js'

/**
 * Every service that opens an async engine must normalise its connection URL.
 *
 * `create_async_engine("postgresql://...")` resolves to psycopg2 -- synchronous,
 * and not a dependency of any service here. The failure is a bare
 * `ModuleNotFoundError: No module named 'psycopg2'` raised at import, eleven
 * frames below anything recognisable, and it does not mention the URL.
 *
 * What that costs when it reaches a deployment: on 2026-08-30 the first
 * deployment of a generated product built its image, pushed it, launched the
 * machine, and then reported only
 *
 *     WARNING The app is not listening on the expected address
 *     - 0.0.0.0:8000
 *
 * after an eleven-minute health-check timeout, restarting ten times before Fly
 * gave up. Nothing in the workflow output named the database, the URL or the
 * driver.
 *
 * The Control Plane had the validator and the product did not -- the Tier B
 * shape: fixed downstream, never promoted. Asserted for both profiles here so
 * the next divergence fails in the factory rather than on a machine somebody
 * has to read the logs of.
 */

const PROFILES = ['product', 'control-plane'] as const

function settingsFor(profile: string): string {
  // Through templatePath, so a file that moves into the shared layer is still
  // found rather than failing as ENOENT on a path that no longer exists. The
  // product's is a template since 2026-09-08, because the generator writes the
  // product code into it; the driver rule it asserts is the same either way.
  try {
    return readFileSync(
      templatePath(profile, 'services', 'api', 'koras_api', 'core', 'settings.py.hbs'),
      'utf8',
    )
  } catch {
    return readFileSync(
      templatePath(profile, 'services', 'api', 'koras_api', 'core', 'settings.py'),
      'utf8',
    )
  }
}

describe.each(PROFILES)('%s: the API normalises its database URL', (profile) => {
  const source = settingsFor(profile)

  it('validates database_url rather than trusting what it is handed', () => {
    expect(source).toContain('@field_validator("database_url"')
  })

  it('rewrites the driverless form every provider actually emits', () => {
    // Supabase, Doppler, psql and the local bootstrap all write this.
    expect(source).toContain('"postgresql://", "postgresql+asyncpg://"')
  })

  it('rewrites the postgres:// alias too, which some providers still emit', () => {
    expect(source).toContain('"postgres://", "postgresql+asyncpg://"')
  })

  /**
   * The driver has to be installed for the rewrite to mean anything, and
   * psycopg2 must not be -- if it were, the original bug would have been a
   * silent synchronous engine inside an async application rather than a loud
   * import error, which is worse.
   */
  it('depends on asyncpg and not on psycopg2', () => {
    const pyproject = readFileSync(templatePath(profile, 'services', 'api', 'pyproject.toml.hbs'), 'utf8')
    expect(pyproject).toContain('asyncpg')
    expect(pyproject).not.toContain('psycopg2')
  })
})
