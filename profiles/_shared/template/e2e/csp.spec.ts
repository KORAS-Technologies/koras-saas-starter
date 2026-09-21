import { expect, test } from '@playwright/test'
import { expectProductionPolicy } from './support/csp'

/**
 * The policy a production build actually serves.
 *
 * R1. `support/csp.ts` holds the invariant and says why one production run
 * covers all four Koras environments; this file names the applications it is
 * asserted against.
 *
 * Every application here is started by this suite's own `webServer` with
 * `next start` over a `next build`, which is what makes the assertion about a
 * production artefact rather than about a template. Nothing here reads a file.
 */

/** The applications this suite starts that emit a policy, and where they are. */
const APPLICATIONS = (process.env.E2E_CSP_ORIGINS ?? '')
  .split(',')
  .map((entry) => entry.trim())
  .filter((entry) => entry !== '')
  .map((entry) => {
    const [label, origin] = entry.split('=')
    return { label: label as string, origin: origin as string }
  })

test('the suite knows which applications to check', () => {
  // Anti-vacuity. A loop over an empty list is a green run that asserted
  // nothing, and this file's whole purpose is one negative claim.
  //
  // A plain expectation rather than `test.fail(count === 0, …)`. That form does
  // work -- it marks the test expected-to-fail, the empty body then passes, and
  // Playwright reports "Expected to fail, but passed" -- but it works *because*
  // the body is empty. The day somebody adds a real assertion here, an empty
  // list makes the body throw, Playwright sees the failure it was told to
  // expect, and the guard silently starts passing.
  expect(APPLICATIONS.length, 'E2E_CSP_ORIGINS named no application').toBeGreaterThan(0)
  for (const application of APPLICATIONS) {
    expect(application.label, 'an origin entry has no label').toBeTruthy()
    expect(application.origin, `${application.label}: no origin`).toMatch(/^https?:\/\//)
  }
})

for (const application of APPLICATIONS) {
  test(`${application.label} serves a production policy with no unsafe-eval`, async ({
    request,
  }) => {
    // `/login` because every application here has one and the middleware
    // matcher covers it: it is a page the application renders itself, not a
    // static asset the matcher excludes.
    const response = await request.get(`${application.origin}/login`)
    expectProductionPolicy(response, application.label)
  })
}
