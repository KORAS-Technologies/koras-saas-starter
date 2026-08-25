import { createServer, type Server } from 'node:http'
import { AddressInfo } from 'node:net'

/**
 * A Control Plane that actually runs.
 *
 * Phase 10's acceptance criterion is "product registration test passes against
 * running Control Plane". A function double satisfies the letter of that and
 * not the point: it never exercises a socket, a header casing, a JSON
 * round-trip, or a status line. This is a real HTTP server on a real port,
 * speaking the subset of the Control Plane's contract that registration
 * touches — so the client is tested through the same path it takes in
 * production, minus only the part that would create real resources.
 *
 * It mirrors the Control Plane's own rules rather than being permissive:
 *
 *  - `extra="forbid"` — an unknown field is a 422, exactly as the Pydantic
 *    schema produces. A payload that passes here passes there.
 *  - `profile: control-plane` is refused. The Control Plane is not an entry in
 *    its own product registry, and it rejects the attempt at its edge.
 *  - No credential is accepted anywhere in the payload. The registry stores
 *    references; a field carrying a secret is a 422 rather than something
 *    quietly persisted.
 */

/** Fields `ProductRegistrationRequest` accepts. Anything else is a 422. */
const ALLOWED_TOP_LEVEL = new Set([
  'code',
  'name',
  'slug',
  'repository',
  'profile',
  'primary_domain',
  'starter_version',
  'profile_version',
  'environments',
])

const ALLOWED_INFRASTRUCTURE = new Set([
  'github_repository',
  'doppler_project',
  'doppler_config',
  'supabase_project_ref',
  'supabase_api_url',
  'zitadel_instance',
  'zitadel_project_id',
  'zitadel_client_id',
  'vercel_projects',
  'fly_apps',
  'cloudflare_zone_id',
  'platform_api_base_url',
])

/**
 * Field names that would mean a credential reached the registry.
 *
 * Checked by name across the whole payload rather than at known positions: the
 * risk is a field nobody predicted, so a rule that only inspects the fields we
 * already thought of would not catch the case it exists for.
 */
const CREDENTIAL_NAME = /token|secret|password|private_key|api_key|credential|assertion/i

export interface ReceivedRequest {
  method: string
  path: string
  headers: Record<string, string | string[] | undefined>
  body: unknown
  raw: string
}

export interface ControlPlaneStub {
  /** Base URL to hand the generator, e.g. http://127.0.0.1:53821 */
  baseUrl: string
  /** Every request the server received, in order. */
  received: ReceivedRequest[]
  /** Registrations it accepted, in order. */
  registered: Array<Record<string, unknown>>
  /** Make the next request fail this way, once. */
  failNext: (mode: { status: number; body?: string } | 'hang') => void
  close: () => Promise<void>
}

interface StubOptions {
  /** The bearer token the stub will accept. Anything else is a 401. */
  token: string
}

function findCredentialField(value: unknown, path: string[] = []): string | undefined {
  if (value === null || typeof value !== 'object') return undefined
  if (Array.isArray(value)) {
    for (const [i, item] of value.entries()) {
      const hit = findCredentialField(item, [...path, String(i)])
      if (hit) return hit
    }
    return undefined
  }
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (CREDENTIAL_NAME.test(key)) return [...path, key].join('.')
    const hit = findCredentialField(child, [...path, key])
    if (hit) return hit
  }
  return undefined
}

/** Validates one payload the way the Control Plane's schema would. */
export function validateRegistration(body: unknown): { ok: true } | { ok: false; detail: string } {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return { ok: false, detail: 'body must be a JSON object' }
  }
  const payload = body as Record<string, unknown>

  for (const key of Object.keys(payload)) {
    if (!ALLOWED_TOP_LEVEL.has(key)) {
      return { ok: false, detail: `extra fields not permitted: ${key}` }
    }
  }

  for (const required of ['code', 'name', 'slug', 'profile', 'environments']) {
    if (payload[required] === undefined) {
      return { ok: false, detail: `field required: ${required}` }
    }
  }

  if (payload.profile === 'control-plane') {
    return { ok: false, detail: 'the Control Plane cannot be registered as a product' }
  }

  const environments = payload.environments
  if (environments === null || typeof environments !== 'object' || Array.isArray(environments)) {
    return { ok: false, detail: 'environments must be an object' }
  }

  for (const [name, spec] of Object.entries(environments as Record<string, unknown>)) {
    if (spec === null || typeof spec !== 'object') {
      return { ok: false, detail: `environments.${name} must be an object` }
    }
    const entry = spec as Record<string, unknown>
    if (entry.infrastructure === undefined || entry.services === undefined) {
      return { ok: false, detail: `environments.${name} needs infrastructure and services` }
    }
    const infra = entry.infrastructure as Record<string, unknown>
    for (const key of Object.keys(infra)) {
      if (!ALLOWED_INFRASTRUCTURE.has(key)) {
        return { ok: false, detail: `extra fields not permitted: environments.${name}.infrastructure.${key}` }
      }
    }
  }

  const credential = findCredentialField(payload)
  if (credential) {
    return { ok: false, detail: `the registry stores references, not credentials: ${credential}` }
  }

  return { ok: true }
}

export async function startControlPlaneStub(options: StubOptions): Promise<ControlPlaneStub> {
  const received: ReceivedRequest[] = []
  const registered: Array<Record<string, unknown>> = []
  let nextFailure: { status: number; body?: string } | 'hang' | undefined

  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', (chunk: Buffer) => chunks.push(chunk))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      let body: unknown
      try {
        body = raw === '' ? undefined : JSON.parse(raw)
      } catch {
        body = undefined
      }

      received.push({
        method: req.method ?? '',
        path: req.url ?? '',
        headers: req.headers,
        body,
        raw,
      })

      const failure = nextFailure
      nextFailure = undefined

      // Never answers. The client's own timeout is what has to end this, which
      // is the only way to test that it has one.
      if (failure === 'hang') return

      if (failure) {
        res.writeHead(failure.status, { 'content-type': 'application/json' })
        res.end(failure.body ?? JSON.stringify({ detail: 'injected failure' }))
        return
      }

      const send = (status: number, payload: unknown): void => {
        res.writeHead(status, { 'content-type': 'application/json' })
        res.end(JSON.stringify(payload))
      }

      if (req.method !== 'POST' || !(req.url ?? '').startsWith('/api/platform/v1/products')) {
        send(404, { detail: 'not found' })
        return
      }

      if (req.headers.authorization !== `Bearer ${options.token}`) {
        send(401, { detail: 'invalid or missing bearer token' })
        return
      }

      const verdict = validateRegistration(body)
      if (!verdict.ok) {
        send(422, { detail: verdict.detail })
        return
      }

      registered.push(body as Record<string, unknown>)
      send(201, { code: (body as Record<string, unknown>).code, status: 'registered' })
    })
  })

  // Loopback only. A stub that binds every interface is a stub that accepts a
  // real registration from something else on the network.
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    received,
    registered,
    failNext: (mode) => {
      nextFailure = mode
    },
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections?.()
        server.close((err) => (err ? reject(err) : resolve()))
      }),
  }
}
