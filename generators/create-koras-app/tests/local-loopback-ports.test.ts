import { describe, it, expect } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * Every host port a generated project's local stack publishes is bound to
 * IPv4 loopback (docs/features/local-zitadel-follow-ups/loopback-local-services.md).
 *
 * The database behind ZITADEL was published on every interface with
 * postgres/postgres, so anyone on the same network could read or write the
 * identity provider's event store. Redis, MinIO, Mailpit, the OTLP collector
 * and the proxy were the same.
 *
 * The rendered compose files are parsed as YAML rather than matched as text,
 * so a line ending, a comment or a quoting style cannot hide a binding, and
 * both the short ("ip:host:container") and the long ({host_ip, published})
 * syntax are read. A port with no host address is a failure: Docker binds it
 * to 0.0.0.0 and [::].
 *
 * An entry in ALLOWED is the only way past this, and it must say why.
 */

const LOOPBACK = '127.0.0.1'

/** `<file>#<service>#<container port>` -> reason. Empty on purpose. */
const ALLOWED: Record<string, string> = {}

interface Variant {
  profile: ProfileName
  label: string
  with?: string[]
  without?: string[]
}

// The default of each profile, plus the component rows Generator Integration
// builds, so a service added behind a component is checked too.
const VARIANTS: Variant[] = [
  { profile: 'product', label: 'default' },
  { profile: 'product', label: 'secure', with: ['secure_files', 'clamd', 'worker', 'data_import', 'ai', 'ai_gateway'] },
  { profile: 'product', label: 'with', with: ['marketing', 'ai_gateway', 'scheduler'] },
  { profile: 'product', label: 'minimal', without: ['admin', 'worker', 'reporting'] },
  { profile: 'control-plane', label: 'default' },
]

function render(v: Variant) {
  const { manifest, defaults } = loadProfile(v.profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, { with: v.with, without: v.without })
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: `loopback-${v.label}`,
    projectSlug: `loopback-${v.label}`,
    profile: v.profile,
    manifest,
    defaults,
    selections,
    outputDir: join(tmpdir(), 'koras-loopback-never-written'),
    dryRun: true,
    provision: false,
  })
  return renderTemplate(ctx)
}

function isComposeFile(path: string): boolean {
  const p = path.replace(/\\/g, '/')
  return /(^|\/)(docker-)?compose[^/]*\.ya?ml$/.test(p) || /\.compose\.ya?ml$/.test(p)
}

/** `${NAME:-default}` -> default, `${NAME}` -> NAME, as compose would with nothing set. */
function interpolate(value: string): string {
  return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}/g, (_m, name: string, def?: string) =>
    def !== undefined ? def : name,
  )
}

interface Binding {
  hostIp: string | null
  container: string
  raw: string
}

/** Reads one `ports:` entry in either compose syntax. */
function parsePort(entry: unknown): Binding {
  if (typeof entry === 'number') return { hostIp: null, container: String(entry), raw: String(entry) }
  if (typeof entry === 'string') {
    const raw = entry
    const value = interpolate(entry).replace(/\/(tcp|udp|sctp)$/, '')
    // [ipv6]:host:container
    const v6 = /^\[([^\]]+)\]:([^:]*):(.+)$/.exec(value)
    if (v6) return { hostIp: v6[1] ?? null, container: v6[3] ?? '', raw }
    const parts = value.split(':')
    if (parts.length >= 3) {
      // ip:host:container, or ip::container. An unbracketed IPv6 address has
      // more than two colons and is read here as "not loopback IPv4".
      const container = parts[parts.length - 1] ?? ''
      const ip = parts.slice(0, parts.length - 2).join(':')
      return { hostIp: ip, container, raw }
    }
    return { hostIp: null, container: parts[parts.length - 1] ?? '', raw }
  }
  if (entry && typeof entry === 'object') {
    const o = entry as Record<string, unknown>
    const hostIp = typeof o.host_ip === 'string' ? interpolate(o.host_ip) : null
    return { hostIp, container: String(o.target ?? ''), raw: JSON.stringify(entry) }
  }
  throw new Error(`unreadable ports entry: ${JSON.stringify(entry)}`)
}

function bindings(variant: Variant) {
  const found: { file: string; service: string; binding: Binding }[] = []
  const files: string[] = []
  for (const file of render(variant)) {
    if (!isComposeFile(file.outputPath)) continue
    const path = file.outputPath.replace(/\\/g, '/')
    files.push(path)
    const doc = yaml.load(String(file.content), { schema: COMPOSE_SCHEMA }) as {
      services?: Record<string, { ports?: unknown[] } | null>
    } | null
    for (const [service, def] of Object.entries(doc?.services ?? {})) {
      for (const entry of def?.ports ?? []) found.push({ file: path, service, binding: parsePort(entry) })
    }
  }
  return { files, found }
}

// Compose's own tags (`!reset`, `!override`) appear in the legacy override.
const COMPOSE_SCHEMA = yaml.DEFAULT_SCHEMA.extend(
  ['!reset', '!override'].flatMap((tag) =>
    (['scalar', 'sequence', 'mapping'] as const).map(
      (kind) => new yaml.Type(tag, { kind, construct: (data: unknown) => data }),
    ),
  ),
)

describe('parsePort', () => {
  it('reads each syntax, and finds no host address where Docker would bind every interface', () => {
    expect(parsePort('127.0.0.1:${KORAS_PORT_X:-54322}:5432').hostIp).toBe('127.0.0.1')
    expect(parsePort('${KORAS_PORT_X:-54322}:5432').hostIp).toBeNull()
    expect(parsePort('5432:5432').hostIp).toBeNull()
    expect(parsePort('0.0.0.0:5432:5432').hostIp).toBe('0.0.0.0')
    expect(parsePort('[::]:5432:5432').hostIp).toBe('::')
    expect(parsePort('127.0.0.1::5432/tcp').hostIp).toBe('127.0.0.1')
    expect(parsePort(5432).hostIp).toBeNull()
    expect(parsePort({ target: 5432, published: 54322 }).hostIp).toBeNull()
    expect(parsePort({ target: 5432, published: 54322, host_ip: '127.0.0.1' }).hostIp).toBe('127.0.0.1')
  })
})

describe('local stack: every published port is on loopback', () => {
  for (const variant of VARIANTS) {
    it(`${variant.profile} (${variant.label})`, () => {
      const { files, found } = bindings(variant)
      // Not vacuous: the base compose file is read and publishes ports.
      expect(files).toContain('local/docker-compose.yml')
      expect(found.length).toBeGreaterThanOrEqual(8)

      const offenders = found
        .filter(({ file, service, binding }) => {
          if (binding.hostIp === LOOPBACK) return false
          return !ALLOWED[`${file}#${service}#${binding.container}`]
        })
        .map(({ file, service, binding }) => `${file} ${service}: "${binding.raw}" (host address ${binding.hostIp ?? 'none: every interface'})`)
      expect(offenders).toEqual([])
    })
  }

  it('the database behind ZITADEL is among the bindings checked', () => {
    for (const profile of ['product', 'control-plane'] as const) {
      const db = bindings({ profile, label: 'default' }).found.filter((f) => f.service === 'supabase-db')
      expect(db.map((d) => d.binding.container)).toEqual(['5432'])
      expect(db[0]?.binding.hostIp).toBe(LOOPBACK)
    }
  })
})
