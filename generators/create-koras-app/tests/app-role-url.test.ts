import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { templatePath } from './template-path.js'

/**
 * The URL `create-app-role.sh` tells an operator to store.
 *
 * A managed pooler routes to a tenant by a suffix on the username: Supavisor
 * reads `postgres.abcdefghijklmnop` as the role `postgres` on project
 * `abcdefghijklmnop`. The script rebuilt the URL by swapping the role in, and
 * took the suffix out with it -- so the pooler had nothing to route by and
 * refused at connect time:
 *
 *     FATAL: (ENOIDENTIFIER) no tenant identifier provided
 *
 * On koras-e2e-shop that surfaced as an API which built, deployed and then
 * failed its health check, with an error naming neither the URL nor this
 * script. Correcting the value by hand worked; re-running the script put the
 * broken one straight back, which is what makes this worth a test rather than
 * a note.
 *
 * The shell is executed rather than pattern-matched: the bug was in parameter
 * expansion, and asserting that the source contains the right expansion is
 * asserting the thing that was already wrong.
 */

const SCRIPT = readFileSync(templatePath('product', 'local/scripts/create-app-role.sh'), 'utf8')

/** Run the script's URL-rebuilding logic alone, without touching a database. */
function rebuild(privileged: string, role = 'koras_app'): string {
  const logic = `
    URL='${privileged}'
    ROLE='${role}'
    proto="\${URL%%://*}"
    rest="\${URL#*://}"
    hostpart="\${rest#*@}"
    userpart="\${rest%%:*}"
    suffix="\${userpart#*.}"
    if [ "$suffix" = "$userpart" ]; then qualified="\${ROLE}"; else qualified="\${ROLE}.\${suffix}"; fi
    printf '%s' "\${proto}://\${qualified}:GENERATED@\${hostpart}"
  `
  return execFileSync('bash', ['-c', logic], { encoding: 'utf8' })
}

describe('the connection URL the script prints', () => {
  it('carries the tenant suffix a pooler routes by', () => {
    expect(rebuild('postgresql://postgres.abcdefghijklmnop:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres')).toBe(
      'postgresql://koras_app.abcdefghijklmnop:GENERATED@aws-0-us-east-1.pooler.supabase.com:5432/postgres',
    )
  })

  /**
   * A direct host has no suffix and needs none. Appending one there would
   * invent a tenant identifier for a server that does not route by them, which
   * is the same bug pointing the other way.
   */
  it('adds no suffix when the privileged username has none', () => {
    expect(rebuild('postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres')).toBe(
      'postgresql://koras_app:GENERATED@db.abcdefghijklmnop.supabase.co:5432/postgres',
    )
  })

  it('keeps host, port and database exactly as the privileged URL had them', () => {
    const out = rebuild('postgresql://postgres.ref:pw@somewhere.example:6543/otherdb')
    expect(out).toContain('@somewhere.example:6543/otherdb')
  })

  it('honours a role name overridden through KORAS_APP_ROLE', () => {
    expect(rebuild('postgresql://postgres.ref:pw@pooler.example:5432/postgres', 'other_role')).toContain(
      '://other_role.ref:',
    )
  })

  /**
   * Guards the guard. The block above is a copy of the script's logic, so it
   * would keep passing if the script stopped doing this at all.
   */
  it('is the logic the script actually contains', () => {
    expect(SCRIPT).toContain('userpart="${rest%%:*}"')
    expect(SCRIPT).toContain('suffix="${userpart#*.}"')
    expect(SCRIPT).toContain('${proto}://${qualified}:${GENERATED}@${hostpart}')
  })
})
