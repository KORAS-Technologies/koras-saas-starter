import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * R-034: the generated API had no rate limiting of any kind.
 *
 * The path worth protecting is the one reachable without credentials -- token
 * verification, which is a JWKS lookup and an asymmetric signature check, and
 * is the most expensive thing the service does. Nothing stood in front of it.
 *
 * Two tiers, because the expensive path runs before there is a caller to name:
 * an unauthenticated tier keyed on the client address, and a per-tenant tier
 * keyed on claims the signature covered.
 */

const PROFILES: ProfileName[] = ['product', 'control-plane']

function render(profile: ProfileName) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: `rl-${profile}`,
    projectSlug: `rl-${profile}`,
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

describe.each(PROFILES)('%s: the API limits what it serves', (profile) => {
  const files = render(profile)

  it('ships the limiter and its tests', () => {
    expect(files.has('python-packages/koras-ratelimit/src/koras_ratelimit/__init__.py')).toBe(true)
    expect(files.has('python-packages/koras-ratelimit/tests/test_ratelimit.py')).toBe(true)
  })

  it('declares it as a dependency of the API, not just as a directory', () => {
    // The defect class this repository already has a comment about: the import
    // resolves locally because something else pulled it in, and the service is
    // built from a manifest that never named it.
    const pyproject = files.get('services/api/pyproject.toml')
    expect(pyproject).toContain('koras-ratelimit')
    expect(pyproject).toContain('redis')
    expect(pyproject).toMatch(/koras-ratelimit\s*=\s*\{\s*workspace\s*=\s*true\s*\}/)
  })

  it('wires both tiers into the API', () => {
    const module = files.get('services/api/koras_api/core/ratelimit.py')
    expect(module, 'core/ratelimit.py is not rendered').toBeDefined()
    expect(module).toMatch(/async def limit_anonymous/)
    expect(module).toMatch(/async def limit_authenticated/)
  })

  it('keys the authenticated tier on claims, never on a header', () => {
    const module = files.get('services/api/koras_api/core/ratelimit.py') ?? ''
    // `sub` and `organization_id` come off a verified token. A tier keyed on
    // anything the caller sends is a tier the caller can reset at will.
    expect(module).toMatch(/claims\.sub/)
    expect(module).toMatch(/claims\.organization_id/)
  })

  it('does not believe X-Forwarded-For unless told to', () => {
    const module = files.get('services/api/koras_api/core/ratelimit.py') ?? ''
    const settings = files.get('services/api/koras_api/core/settings.py') ?? ''
    expect(module).toMatch(/trust_forwarded_for/)
    // Default false: trusting it where no proxy rewrites it gives a caller a
    // fresh quota per request, which limits nobody while appearing to work.
    expect(settings).toMatch(/trust_forwarded_for:\s*bool\s*=\s*False/)
  })

  it('applies the unauthenticated tier to the API, and not to health', () => {
    const main = files.get('services/api/koras_api/main.py') ?? ''
    expect(main).toMatch(/dependencies=\[Depends\(limit_anonymous\)\]/)
    // Health must stay reachable: limiting a load balancer probe takes the
    // service out of rotation, which is a self-inflicted outage.
    const healthLine = main.split('\n').find((l) => l.includes('health.router')) ?? ''
    expect(healthLine).not.toContain('limit_anonymous')
  })

  it('opens a Redis connection for it, and closes it', () => {
    const main = files.get('services/api/koras_api/main.py') ?? ''
    expect(main).toMatch(/app\.state\.redis/)
    expect(main).toMatch(/aclose\(\)/)
  })

  it('treats an absent Redis as degraded rather than as an error', () => {
    // The API runs locally and in tests with no Redis at all. Failing there
    // would make the limiter a hard dependency of running the service.
    const limiter = files.get('python-packages/koras-ratelimit/src/koras_ratelimit/__init__.py') ?? ''
    expect(limiter).toMatch(/degraded/)
    const settings = files.get('services/api/koras_api/core/settings.py') ?? ''
    expect(settings).toMatch(/redis_url:\s*str\s*=\s*""/)
  })

  it('counts in Redis rather than in the process', () => {
    // An in-process counter is a per-machine counter: it multiplies the real
    // limit by the machine count and loosens every time the service scales out.
    const limiter = files.get('python-packages/koras-ratelimit/src/koras_ratelimit/__init__.py') ?? ''
    expect(limiter).toMatch(/async def check/)
    expect(limiter).toMatch(/\.incr\(/)
    expect(limiter).toMatch(/\.expire\(/)
  })
})
