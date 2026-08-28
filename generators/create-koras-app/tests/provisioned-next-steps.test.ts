import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { provisionedNextSteps } from '../src/cli/index.js'

/**
 * What the tool says to do once an estate exists.
 *
 * It said `cd <slug>` and `make bootstrap`, which is the local Docker stack —
 * the right next step for a generated project and the wrong one for a
 * provisioned estate. Terraform creates the Doppler project and its four
 * configs and writes no setting into them; it cannot, knowing neither the
 * Supabase password nor the ZITADEL service token.
 *
 * So an apply that succeeded completely left every Doppler config empty, and
 * the tool's own instructions led away from the four commands that fill them.
 * There was no error: the only sign was an empty Secrets tab, which someone
 * found by opening it and asking.
 *
 * The runbook had the steps the whole time. Nothing pointed at them, and the
 * output people actually read is this one.
 */

const ROOT = join(__dirname, '..', '..', '..')

describe('the next steps printed after provisioning', () => {
  const lines = provisionedNextSteps('koras-e2e-shop')
  const text = lines.join('\n')

  it('names each command that fills Doppler', () => {
    // Individually, so that dropping one fails here rather than reading as a
    // shorter list that still looks complete.
    expect(text).toContain('local/scripts/create-app-role.sh')
    expect(text).toContain('local/scripts/doppler-bootstrap.sh --dry-run')
    expect(text).toContain('make doppler-bootstrap')
    expect(text).toContain('make doppler-bootstrap-prod')
    expect(text).toContain('make doppler-check')
  })

  it('puts the database role before the bootstrap that asks for its output', () => {
    // doppler-bootstrap prompts for DATABASE_URL and DATABASE_ADMIN_URL, and
    // create-app-role.sh is what produces them. The other order asks for values
    // that do not exist yet.
    expect(text.indexOf('create-app-role.sh')).toBeLessThan(text.indexOf('doppler-bootstrap.sh'))
  })

  it('names prod separately, because the default target skips it', () => {
    // `make doppler-bootstrap --environment prod` does not reach the script:
    // make consumes the option and reads prod as a target name, so the default
    // set runs and production is silently skipped.
    expect(text).toMatch(/make doppler-bootstrap\n\s*make doppler-bootstrap-prod/)
  })

  it('says what `make bootstrap` is, rather than leaving it as the next step', () => {
    expect(text).toContain('local Docker stack')
  })

  it('leads with the project directory', () => {
    expect(text).toContain('cd koras-e2e-shop')
  })

  it('names commands the generated project actually has', () => {
    // The scripts are named from the starter's templates, so a rename there
    // would otherwise leave this pointing at files no generated project holds.
    const shared = join(ROOT, 'profiles', '_shared', 'template', 'local', 'scripts')
    const present = readdirSync(shared)
    expect(present).toContain('create-app-role.sh')
    expect(present.some((f) => f.startsWith('doppler-bootstrap.sh'))).toBe(true)

    // And the make targets exist. One Makefile, in _shared, which both
    // profiles render -- so this is the only copy to check.
    const makefile = readFileSync(
      join(ROOT, 'profiles', '_shared', 'template', 'Makefile.hbs'),
      'utf8',
    )
    expect(makefile).toContain('doppler-bootstrap-prod:')
    expect(makefile).toContain('doppler-check:')
  })
})
