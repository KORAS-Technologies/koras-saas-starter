import { describe, it, expect, beforeAll } from 'vitest'
import { join } from 'node:path'
import { loadProfile } from '../src/profiles/index.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * The API sets security headers, and until TS-13 it set none.
 *
 * The Next applications set theirs in `next.config`. The API -- which is the
 * thing actually holding the data -- set nothing, in every generated project.
 * A browser reaching a JSON endpoint directly got no `nosniff`, no
 * frame-ancestors and no referrer policy.
 *
 * Promoted from koras-control-plane. Only the headers came: that repository's
 * module also carries a rate limiter, and `koras_ratelimit` already does that
 * here in Redis with a two-tier design. Two limiters disagreeing about one
 * request is worse than either alone.
 */

function render(profile: 'product' | 'control-plane'): Map<string, string> {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: `a-${profile}`,
    projectSlug: `a-${profile}`,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: join(__dirname, 'unused'),
    dryRun: true,
    provision: false,
  })
  return new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content.toString()]))
}

const MODULE = 'services/api/koras_api/core/security.py'
const MAIN = 'services/api/koras_api/main.py'

describe.each(['product', 'control-plane'] as const)('%s: API security headers', (profile) => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render(profile)
  })

  it('ships the middleware', () => {
    expect(files.get(MODULE), `${MODULE} is not rendered`).toBeDefined()
  })

  it('registers it, so the headers reach a response at all', () => {
    // A module nothing adds is a module that sets no headers, and the file
    // existing is the easiest thing to mistake for the feature working.
    const main = files.get(MAIN) ?? ''
    expect(main).toContain('from .core.security import SecurityHeadersMiddleware')
    expect(main).toContain('app.add_middleware(SecurityHeadersMiddleware)')
  })

  it('sets the headers that matter on a JSON API', () => {
    const module = files.get(MODULE) ?? ''
    for (const header of [
      'X-Content-Type-Options',
      'X-Frame-Options',
      'Referrer-Policy',
      'Content-Security-Policy',
    ]) {
      expect(module, `${header} is not set`).toContain(header)
    }
  })

  it('sets them on responses a handler did not finish', () => {
    // A 500 rendered without `nosniff` is still a response a browser will guess
    // a type for, and those are the responses most worth protecting.
    // BaseHTTPMiddleware wraps the whole call, so an error is covered -- which
    // is why this asserts the middleware shape rather than a decorator on
    // successful routes.
    const module = files.get(MODULE) ?? ''
    expect(module).toMatch(/class SecurityHeadersMiddleware\(BaseHTTPMiddleware\)/)
    expect(module).toMatch(/response = await call_next\(request\)/)
  })

  it('does not send HSTS from a local http listener', () => {
    // It pins the developer's browser to https for localhost and breaks every
    // other project on that machine -- and removing the header again does not
    // undo it.
    const module = files.get(MODULE) ?? ''
    expect(module).toMatch(/settings\.environment\.value != ["']dev["']/)
  })

  it('brings no second rate limiter with it', () => {
    // koras_ratelimit and core/ratelimit.py already do this, in Redis, across
    // more than one machine. The in-process limiter this module carries
    // downstream is deliberately left there.
    const module = files.get(MODULE) ?? ''
    expect(module, 'a rate limiter came with the headers').not.toMatch(
      /class RateLimitMiddleware|RateLimit-Limit|Too many requests/,
    )
  })
})
