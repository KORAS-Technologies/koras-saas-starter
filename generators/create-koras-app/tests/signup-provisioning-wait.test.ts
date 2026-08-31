import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A signup that ends in the browser, rather than in an inbox.
 *
 * Verifying an address starts a provisioning run and the run takes minutes: a
 * ZITADEL organisation, an owner, two project grants, a tenant, a subscription.
 * The page used to say "we will email you when it is ready" and stop -- a dead
 * end at the exact moment somebody has finished committing to the product, and
 * the most common place to lose them.
 *
 * It waits with them now and sends them on. These assert the two decisions in
 * that which are easy to undo by accident.
 */

const SIGNUP = join(
  __dirname, '..', '..', '..',
  'profiles', 'product', 'template', 'apps', 'web', 'src', 'app', 'signup',
)

function read(...segments: string[]): string {
  return readFileSync(join(SIGNUP, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the wait after verification', () => {
  const waiting = read('ProvisioningStatus.tsx.hbs')

  /**
   * The destination, and the reason it is not `/dashboard`.
   *
   * A customer has a ZITADEL account by then and no session with this
   * application -- nothing has signed them in and nothing on this page can.
   * `/dashboard` would bounce off the session gate to the sign-in page anyway,
   * one confusing flash later, so the redirect goes there directly and carries
   * the dashboard as its destination.
   */
  it('sends them to sign in, with the dashboard as the destination', () => {
    expect(waiting).toContain('/login?next=%2Fdashboard')
    expect(waiting, 'a bare /dashboard redirect bounces off the session gate').not.toMatch(
      /assign\(['"]\/dashboard/,
    )
  })

  /**
   * A page that polls forever holds a connection open on a tab nobody is
   * watching. The welcome email is sent by the run itself, so giving up in the
   * browser costs nothing.
   */
  it('stops polling eventually', () => {
    expect(waiting).toContain('GIVE_UP_MS')
    expect(waiting).toMatch(/startedAt\.current > GIVE_UP_MS/)
  })

  it('clears its timer when it unmounts', () => {
    // Otherwise a customer who navigates away leaves a poll running against
    // the Control Plane for as long as the tab lives.
    expect(waiting).toContain('clearTimeout')
    expect(waiting).toContain('cancelled = true')
  })

  it('is the component the verify page hands the verified state to', () => {
    const verify = read('verify', 'page.tsx.hbs')
    expect(verify).toContain('ProvisioningStatus')
    expect(verify).toContain('outcome.jobId')
    expect(verify).toContain('outcome.organizationSlug')
  })
})

describe('the status action', () => {
  const actions = read('actions.ts.hbs')

  /**
   * Polling runs on the server for the same reason every other call in this
   * file does: `KORAS_CONTROL_PLANE_URL` and the shape of that API are not the
   * browser's business, and a page polling the platform directly would put its
   * address in every visitor's network tab.
   */
  it('reaches the Control Plane from the server', () => {
    expect(actions).toContain("'use server'")
    expect(actions).toContain('/api/signup/v1/registrations/status')
    expect(actions).toContain("cache: 'no-store'")
  })

  /**
   * A page that stops waiting because one request timed out is worse than one
   * that keeps waiting: the run is almost certainly still going and the
   * customer cannot restart it.
   */
  it('treats a failed request as still pending, never as a failure', () => {
    const body = actions.slice(actions.indexOf('export async function signupStatus'))
    const catchBlock = body.slice(body.indexOf('} catch'))
    expect(catchBlock).toContain("state: 'pending'")
    expect(catchBlock).toContain('failed: false')
  })

  /**
   * `'use server'` files may export only async functions, so the shape lives
   * beside `SignupState` rather than next to the function that returns it.
   */
  it('keeps its type out of the server-action module', () => {
    expect(read('state.ts')).toContain('export interface SignupStatus')
    expect(actions).not.toMatch(/^export interface SignupStatus/m)
  })
})
