import { expect, type APIResponse } from '@playwright/test'

/**
 * What a production response's Content-Security-Policy must say.
 *
 * R1. Every other check on this policy in this repository reads a template: the
 * middleware source, or the file a generation wrote. Those prove what the
 * source says, and the thing that matters is what a built application actually
 * sends -- a distinction that stops being academic the moment a policy is
 * assembled conditionally. GR-248 proposes exactly that: a development-only
 * `'unsafe-eval'`, compiled out of a production build because Next inlines
 * `process.env.NODE_ENV`. "Compiled out" is a claim about a build, and this is
 * the only assertion in the estate that reads the built artefact's own output.
 *
 * **Why one production guard covers dev, test, stg and prod.** Every Koras
 * environment reaches a browser through `vercel build --prod`, so all four are
 * the same Next production build differing only in configuration. The invariant
 * under test is a property of that build mode, not of an environment name, so
 * running it four times would repeat one measurement rather than make four.
 * What differs per environment is the *configuration*, and that is
 * PLAT-DEF-014's job: it stops a forbidden name entering the inputs. The two
 * are layered and neither substitutes for the other -- PLAT-DEF-014 cannot see
 * a policy assembled wrongly in code, and this cannot see a `NODE_ENV` that
 * should never have been in Doppler.
 */

/** `'nonce-<base64ish>'`, the form a CSP source expression takes. */
const NONCE_TOKEN = /^'nonce-[A-Za-z0-9+/_-]{16,}={0,2}'$/

/** One directive of a policy, split into its name and its source expressions. */
function directives(policy: string): Map<string, string[]> {
  const found = new Map<string, string[]>()
  for (const part of policy.split(';')) {
    const [name, ...tokens] = part.trim().split(/\s+/)
    if (name === undefined || name === '') continue
    const existing = found.get(name.toLowerCase())
    // Kept rather than overwritten: a second `script-src` is a contradiction
    // worth failing on, and a map that silently replaced the first would hide
    // exactly the policy that was hardest to reason about.
    found.set(name.toLowerCase(), existing === undefined ? tokens : [...existing, ';', ...tokens])
  }
  return found
}

/**
 * Assert the production policy on a response that really came from the app.
 *
 * `label` names the application, so a failure says which of four it was.
 */
export function expectProductionPolicy(response: APIResponse, label: string): void {
  // Anti-vacuity, and it comes first. A 404 or a 502 from a proxy can carry a
  // perfectly good-looking header while proving nothing about the application,
  // and a suite that accepted one would report success for an app that never
  // started.
  expect(response.status(), `${label}: not an application response`).toBe(200)

  const headers = response.headers()
  const policy = headers['content-security-policy']
  expect(policy, `${label}: no enforced Content-Security-Policy header`).toBeTruthy()

  // Report-only is not the policy. It is advisory, the browser enforces
  // nothing, and accepting it here would let a change that downgraded
  // enforcement pass as though nothing had happened.
  expect(
    headers['content-security-policy-report-only'],
    `${label}: policy served report-only`,
  ).toBeUndefined()

  const found = directives(policy as string)
  const scriptSrc = found.get('script-src')
  expect(scriptSrc, `${label}: no script-src directive`).toBeDefined()
  const tokens = scriptSrc as string[]

  // A second `script-src` would make the policy's meaning depend on which one
  // the browser honours, which is the first.
  expect(tokens, `${label}: more than one script-src directive`).not.toContain(';')

  // Lowercased, because a keyword-source is matched ASCII case-insensitively:
  // a browser honours `'UNSAFE-EVAL'` exactly as it honours `'unsafe-eval'`,
  // and a comparison that did not would have accepted a policy that grants it.
  const keywords = tokens.map((token) => token.toLowerCase())

  // The property this exists for. Over `script-src`'s own tokens rather than
  // the whole header: `'unsafe-eval'` in `style-src` is a different, and much
  // less alarming, sentence.
  expect(keywords, `${label}: production script-src carries 'unsafe-eval'`).not.toContain(
    "'unsafe-eval'",
  )
  expect(keywords, `${label}: production script-src carries 'unsafe-inline'`).not.toContain(
    "'unsafe-inline'",
  )

  // `script-src-elem` and `script-src-attr` override `script-src` for the
  // things they cover, so an `'unsafe-eval'` in either is fully effective and
  // invisible to the check above. This policy declares neither, and a build
  // that started to is a change worth stopping on rather than reasoning about.
  for (const narrower of ['script-src-elem', 'script-src-attr']) {
    expect(found.has(narrower), `${label}: unexpected ${narrower}, which overrides script-src`).toBe(
      false,
    )
  }

  expect(keywords, `${label}: script-src lost 'strict-dynamic'`).toContain("'strict-dynamic'")

  // Exactly one nonce, in the real token form. Asserting the substring
  // `nonce-` would pass on `'nonce-'` with nothing after it, which is a policy
  // that admits no inline script at all.
  const nonces = tokens.filter((token) => token.startsWith("'nonce-"))
  expect(nonces, `${label}: expected exactly one nonce source`).toHaveLength(1)
  expect(nonces[0], `${label}: nonce is not a usable source expression`).toMatch(NONCE_TOKEN)
}
