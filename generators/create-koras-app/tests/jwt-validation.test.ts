import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * What every generated project checks before it believes a token.
 *
 * The factory ships the only copy of this code, so a verification option
 * missing here is missing from every project generated afterwards — and it is
 * the kind of omission that never surfaces as a bug report, because a token
 * that is accepted when it should not be looks exactly like one that should.
 *
 * There are two verification paths and they had drifted apart:
 *
 *   session cookie   jwtVerify(token, secret, { issuer, algorithms })
 *   ZITADEL id_token jwtVerify(token, jwks,   { audience })
 *
 * The cookie path — the one this application signs itself, and therefore the
 * one it has least reason to distrust — was the stricter of the two. The
 * id_token path, which accepts input from outside, checked the audience and
 * neither the issuer nor the algorithm.
 *
 * Not directly exploitable: the keys come from that instance's JWKS, so a
 * token signed by anyone else fails the signature. But it is required by OIDC
 * Core §3.1.3.7, and "the next check would have caught it" is the argument
 * that removes every check one at a time.
 *
 * Asserted against rendered output rather than the template, because what
 * matters is what a generated project contains.
 */

const PROFILES: ProfileName[] = ['product', 'control-plane']

function render(profile: ProfileName) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: `jwt-${profile}`,
    projectSlug: `jwt-${profile}`,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: '.',
    dryRun: true,
    provision: false,
  })
  return new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content.toString()]))
}

/**
 * The options object of the `jwtVerify` call that takes a JWKS.
 *
 * Located by the key set argument rather than by line number or by the name of
 * the enclosing function, so that renaming `resolveToken` or moving it does not
 * quietly stop this from checking anything.
 */
function idTokenVerifyOptions(source: string): string {
  const match = source.match(/jwtVerify\(\s*[\w.]+\s*,\s*jwksFor\([^)]*\)\s*,\s*\{([\s\S]*?)\}\s*\)/)
  return match?.[1] ?? ''
}

/** The options object of the `jwtVerify` call that takes the local signing key. */
function sessionVerifyOptions(source: string): string {
  const match = source.match(
    /jwtVerify\(\s*[\w.]+\s*,\s*signingKey\([^)]*\)\s*,\s*\{([\s\S]*?)\}\s*\)/,
  )
  return match?.[1] ?? ''
}

describe.each(PROFILES)('%s: a token is verified before it is believed', (profile) => {
  const files = render(profile)
  const source = files.get('packages/auth/src/index.ts')

  it('ships the auth package this asserts about', () => {
    // Without this the regexes below would find nothing and every assertion
    // would pass against an empty string.
    expect(source, 'packages/auth/src/index.ts is not rendered').toBeDefined()
  })

  it('verifies the id_token against the provider key set', () => {
    expect(source).toMatch(/jwtVerify\(\s*[\w.]+\s*,\s*jwksFor\(/)
  })

  describe('the id_token path', () => {
    const options = idTokenVerifyOptions(source ?? '')

    it('is found at all', () => {
      expect(options, 'no jwtVerify(..., jwksFor(...), {...}) call found').not.toBe('')
    })

    it('checks the audience, so another client token is not accepted', () => {
      expect(options).toMatch(/\baudience\b/)
    })

    it('checks the issuer, so another instance token is not accepted', () => {
      // OIDC Core §3.1.3.7 step 3. The JWKS makes a foreign signature fail
      // anyway; this is the check that does not depend on that being true.
      expect(options).toMatch(/\bissuer\b/)
    })

    it('pins the algorithm, so the header cannot choose it', () => {
      expect(options).toMatch(/\balgorithms\b/)
    })

    it('pins it to the asymmetric algorithm ZITADEL signs with', () => {
      expect(options).toMatch(/algorithms:\s*\[\s*'RS256'\s*\]/)
    })
  })

  describe('the session cookie path', () => {
    const options = sessionVerifyOptions(source ?? '')

    it('is found at all', () => {
      expect(options, 'no jwtVerify(..., signingKey(...), {...}) call found').not.toBe('')
    })

    it('checks the issuer', () => {
      expect(options).toMatch(/\bissuer\b/)
    })

    it('pins the algorithm to the symmetric one it signs with', () => {
      // The cookie is signed by this application with a shared secret. Leaving
      // the algorithm open is what makes `alg: none` worth trying.
      expect(options).toMatch(/algorithms:\s*\[\s*'HS256'\s*\]/)
    })
  })

  it('never decodes a token without verifying it', () => {
    // `decodeJwt` reads the claims and checks nothing. A single call in
    // application code is a session built on an unverified assertion, which is
    // the defect the session reader was written to remove.
    expect(source).not.toMatch(/\bdecodeJwt\b/)
  })
})

describe.each(PROFILES)('%s: the API verifies tokens as strictly as the web tier', (profile) => {
  const files = render(profile)
  const source = files.get('services/api/koras_api/core/auth.py')

  it('ships the API auth module this asserts about', () => {
    expect(source, 'services/api/koras_api/core/auth.py is not rendered').toBeDefined()
  })

  it('pins the issuer when it verifies a token', () => {
    // `verify_token` takes `issuer` and defaults it to None, so the check is
    // opt-in and the caller is the only thing that can opt in. The TypeScript
    // tier had the same gap; a fix applied to one language and not the other
    // leaves the same door open on the service that holds the data.
    expect(source).toMatch(/verify_token\([\s\S]*?issuer\s*=/)
  })

  it('still pins the audience it already pinned', () => {
    expect(source).toMatch(/verify_token\([\s\S]*?client_id\s*=/)
  })
})

describe.each(PROFILES)('%s: the shared verifier pins the algorithm', (profile) => {
  const source = render(profile).get(
    'python-packages/koras-auth/src/koras_auth/__init__.py',
  )

  it('is rendered', () => {
    expect(source, 'koras_auth is not rendered').toBeDefined()
  })

  it('never lets the token header choose the algorithm', () => {
    expect(source).toMatch(/algorithms\s*=\s*\[\s*"RS256"\s*\]/)
    expect(source).not.toMatch(/algorithms\s*=\s*None/)
  })

  it('checks the audience itself rather than trusting the decoder', () => {
    // `verify_aud` is switched off in the decode options because python-jose
    // refuses a multi-audience token outright, so the comparison is done by
    // hand afterwards. That is fine -- as long as it is actually done.
    expect(source).toMatch(/presented\s*&\s*allowed/)
  })
})

describe.each(PROFILES)('%s: the local checks cover both languages', (profile) => {
  const scripts = JSON.parse(render(profile).get('package.json') ?? '{}').scripts ?? {}

  /**
   * A generated project is half Python, and its CI runs ruff, mypy and pytest.
   * Its `pnpm lint`, `pnpm typecheck` and `pnpm test` ran only the JavaScript
   * half, so a developer following the repository's own Required Verification
   * could see three green commands over unverified Python.
   *
   * That is not hypothetical: it is how a ruff failure reached the remote in
   * the starter (R-035), which has the same shape and had the same gap.
   */
  it.each([
    ['lint', 'ruff'],
    ['typecheck', 'mypy'],
    ['test', 'pytest'],
  ])('%s reaches the Python half', (task, tool) => {
    const composed = String(scripts[task] ?? '')
    const delegate = String(scripts[`${task}:py`] ?? '')

    expect(composed, `${task} does not run its Python half`).toContain(`${task}:py`)
    expect(delegate, `${task}:py does not run ${tool}`).toContain(tool)
  })

  it('keeps each half runnable on its own', () => {
    // So a failure says which language it came from, and so a JavaScript-only
    // change need not wait for pytest.
    expect(scripts['lint:py']).toBeDefined()
    expect(scripts['typecheck:py']).toBeDefined()
    expect(scripts['test:py']).toBeDefined()
  })
})

describe.each(PROFILES)('%s: the API surface is asserted, not assumed', (profile) => {
  const files = render(profile)

  it('ships the surface tests', () => {
    expect(files.has('tests/security/test_api_surface.py')).toBe(true)
  })

  it('can import the app from the root suite', () => {
    // The API is a workspace member, which makes it buildable. Without also
    // being a dependency of the root it is not installed there, and every test
    // about the API had to read its source rather than ask the app.
    const pyproject = files.get('pyproject.toml') ?? ''
    expect(pyproject).toMatch(/-api",/)
    expect(pyproject).toMatch(/-api"\s*=\s*\{\s*workspace\s*=\s*true\s*\}/)
  })

  it('keeps the shared database module free of tenant imports', () => {
    // `core/database.py` is shared, and the Control Plane has no `.tenant`.
    // The import was dead there until a startup check made it live, and the
    // API stopped importing at all -- `ignore_missing_imports` kept mypy quiet
    // and nothing imported the app to find out.
    const shared = files.get('services/api/koras_api/core/database.py') ?? ''
    expect(shared, 'core/database.py is not rendered').not.toBe('')

    if (profile === 'product') {
      // A product ships its own copy, which is how a shared path is overridden
      // deliberately.
      expect(shared).toMatch(/from \.tenant import TenantDep/)
      expect(shared).toMatch(/async def get_db/)
    } else {
      expect(shared).not.toMatch(/from \.tenant import/)
      expect(shared).toMatch(/async def get_session/)
    }
  })
})

describe('no application decodes a token for itself', () => {
  it.each(PROFILES)('%s: only the auth package verifies tokens', (profile) => {
    // The applications had their own cookie reader once, decoding without
    // verifying and looking for a claim that was no longer there. One reader
    // of one cookie is the invariant; this is what holds it.
    const offenders = [...render(profile).entries()]
      .filter(([path]) => /^(apps|services)\/.*\.tsx?$/.test(path))
      .filter(([, content]) => /\bdecodeJwt\b|\bjwtVerify\b/.test(content))
      .map(([path]) => path)

    expect(offenders, 'token verification belongs in packages/auth').toEqual([])
  })
})
