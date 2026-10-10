import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir, hostname } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs'
import { createHash } from 'node:crypto'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

/**
 * Phase 4.3A: a secure local ZITADEL (PHASE4.3-SPEC v2, ADRs 0015-0017).
 *
 * Every module is imported from a *generated* project, so what is tested is
 * what a product receives. Nothing here talks to Docker, Doppler or a real
 * ZITADEL: stack.mjs takes every effect through `deps`, and the suite drives
 * it against a fake estate -- an in-memory Doppler, a docker that records its
 * calls, and a ZITADEL that answers over a fake HTTP. gpg is real where it is
 * installed, with a synthetic key generated here and thrown away: leg 2's
 * whole claim is about what gpg does, so a stub would prove nothing.
 *
 * Test ids are the spec's (T-U*, T-E*). The T-I* cases need Docker and run in
 * the `local-zitadel-secure` job of generator-integration.yml.
 */

const OUT = join(tmpdir(), `koras-zitadel-secure-${process.pid}-${Date.now()}`)
const PLACEHOLDER = ['Masterkey', 'NeedsToHave32Characters'].join('')
const DEFAULT_PASSWORD = ['Password', '1!'].join('')
const gpgAvailable = spawnSync('gpg', ['--version']).status === 0
const NOW = new Date('2026-10-09T12:00:00Z')

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

async function generate(
  profile: ProfileName,
  slug: string,
  overrides: { with?: string[]; without?: string[] } = {},
) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, overrides)
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  const root = join(OUT, slug)
  return { root, fileList, read: (rel: string) => readFileSync(join(root, rel), 'utf8') }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Module = any

async function load(root: string, rel: string): Promise<Module> {
  return import(pathToFileURL(join(root, rel)).href)
}

function sha256(value: string | Buffer): string {
  return createHash('sha256').update(value).digest('hex')
}

/**
 * A directory on a different device from the temporary directory, used only
 * as the "user profile" a backup directory is compared against. Stat only:
 * nothing is written there.
 */
function otherVolume(): string | null {
  const tmpDev = statSync(tmpdir()).dev
  const candidates =
    process.platform === 'win32'
      ? 'DEFGHIJ'.split('').map((letter) => `${letter}:\\`)
      : ['/dev/shm', '/run', '/boot']
  for (const candidate of candidates) {
    try {
      if (statSync(candidate).dev !== tmpDev) return candidate
    } catch {
      // absent
    }
  }
  return null
}
const OTHER_VOLUME = otherVolume()

/** A throwaway OpenPGP key: certify-only primary plus an encryption subkey. */
async function syntheticRecipient(root: string) {
  const backup = await load(root, 'local/zitadel/escrow-backup.mjs')
  const style = backup.gpgPathStyle()
  // Short on purpose: gpg-agent's socket lives in the home directory, and a
  // socket path past about 108 characters fails to bind -- the suite's own
  // scratch directory is long enough to hit that on Windows.
  const home = mkdtempSync(join(tmpdir(), 'kzg-'))
  if (process.platform !== 'win32') chmodSync(home, 0o700)
  const gpg = (args: string[], input?: string) =>
    spawnSync('gpg', ['--homedir', backup.toGpgPath(home, style), '--batch', '--passphrase', '', ...args], {
      encoding: 'utf8',
      input,
    })
  gpg(['--quick-gen-key', 'KORAS synthetic recovery <synthetic@example.invalid>', 'rsa3072', 'cert', '0'])
  const fingerprint = /^fpr:+([0-9A-F]{40}):/m.exec(gpg(['--with-colons', '--list-keys']).stdout)?.[1]
  if (!fingerprint) throw new Error('could not create a synthetic recovery key')
  gpg(['--quick-add-key', fingerprint, 'rsa3072', 'encr', '0'])
  const armored = gpg(['--armor', '--export', fingerprint]).stdout
  const decrypt = (file: string) =>
    spawnSync('gpg', ['--homedir', backup.toGpgPath(home, style), '--batch', '--decrypt', backup.toGpgPath(file, style)], {
      encoding: 'utf8',
    }).stdout
  const close = () => {
    spawnSync('gpgconf', ['--homedir', backup.toGpgPath(home, style), '--kill', 'gpg-agent'])
    rmSync(home, { recursive: true, force: true })
  }
  return { fingerprint, armored, decrypt, close, home }
}

// ── The fake estate ──────────────────────────────────────────────────────────

interface Call {
  command: string
  args: string[]
  env?: NodeJS.ProcessEnv
}

function fakeEstate(root: string, options: { dopplerConfigs?: string[] } = {}) {
  const koras = mkdtempSync(join(OUT, 'koras-home-'))
  const backupDir = mkdtempSync(join(OUT, 'escrow-backup-'))
  writeFileSync(join(root, 'local', '.env'), 'KORAS_PORT_ZITADEL=18080\nKORAS_PORT_ZITADEL_LOGIN=18081\n')

  const doppler = new Map<string, Map<string, string>>()
  for (const config of options.dopplerConfigs ?? []) doppler.set(config, new Map())
  const events: string[] = []
  const calls: Call[] = []
  const logs: string[] = []
  const world = {
    dbExists: false,
    running: false,
    instanceId: '391000000000000001',
    failInstanceRead: false,
    runningInstanceId: null as string | null,
    stepsSeen: null as string | null,
    tokens: new Map<string, { id: string; userId: string; expires: string }>(),
    tokenCounter: 0,
  }
  const issuer = 'http://localhost:18080'
  const login = 'http://localhost:18081/ui/v2/login/'

  const issueToken = (userId: string, expires: string) => {
    world.tokenCounter += 1
    const token = `synthetic-token-${world.tokenCounter}`
    world.tokens.set(token, { id: `tok-${world.tokenCounter}`, userId, expires })
    return token
  }

  const option = (args: string[], name: string) => args[args.indexOf(name) + 1]
  const ok = (stdout = '') => ({ status: 0, stdout, stderr: '' })

  const exec = (command: string, args: string[], opts: { input?: string; env?: NodeJS.ProcessEnv } = {}) => {
    calls.push({ command, args, env: opts.env })
    if (command === 'doppler') {
      const config = option(args, '--config')
      if (args[0] === 'configs' && args[1] === 'get') {
        return doppler.has(args[2]) ? ok(JSON.stringify({ name: args[2], environment: 'dev' })) : { status: 1, stdout: '', stderr: 'not found' }
      }
      const store = doppler.get(config)
      if (!store) return { status: 1, stdout: '', stderr: 'no config' }
      if (args[0] === 'secrets' && args.includes('--only-names')) {
        return ok(JSON.stringify(Object.fromEntries([...store.keys()].map((k) => [k, {}]))))
      }
      if (args[0] === 'secrets' && args[1] === 'get') return ok(`${store.get(args[2]) ?? ''}\n`)
      if (args[0] === 'secrets' && args[1] === 'set') {
        events.push(`doppler set ${args[2]}`)
        store.set(args[2], opts.input ?? '')
        return ok()
      }
      return { status: 2, stdout: '', stderr: 'unexpected doppler call' }
    }
    if (command === 'docker') {
      if (args[1] === 'version') return ok('2.30.3\n')
      const verb = args.find((a) => ['up', 'exec', 'stop', 'restart', 'down', 'ps', 'pull'].includes(a))
      const init = args.some((a) => a.endsWith('docker-compose.init.yml'))
      const legacy = args.some((a) => a.endsWith('docker-compose.legacy-zitadel.yml'))
      if (verb === 'exec') return ok(world.dbExists ? '1\n' : '\n')
      if (verb === 'up' && args.includes('--wait') && args.includes('supabase-db') && !args.includes('zitadel')) return ok()
      if (verb === 'up' && init) {
        events.push('start-from-init')
        const steps = opts.env?.KORAS_ZITADEL_INIT_STEPS_FILE
        world.stepsSeen = steps && existsSync(steps) ? readFileSync(steps, 'utf8') : null
        const expires = opts.env?.KORAS_ZITADEL_PAT_EXPIRES_AT ?? ''
        world.dbExists = true
        world.running = true
        world.runningInstanceId = world.instanceId
        const machineFile = join(root, 'local', 'zitadel', 'machinekey', 'pat')
        const loginFile = join(root, 'local', 'zitadel', 'bootstrap', 'login-client.pat')
        if (!existsSync(machineFile)) writeFileSync(machineFile, issueToken('machine-user', expires))
        if (!existsSync(loginFile)) writeFileSync(loginFile, issueToken('login-client-user', expires))
        return ok()
      }
      if (verb === 'up') {
        events.push(legacy ? 'start (legacy)' : 'start')
        if (!world.dbExists) return { status: 1, stdout: '', stderr: 'zitadel: database not initialised' }
        world.running = true
        return ok()
      }
      if (verb === 'stop') {
        events.push('stop')
        world.running = false
        return ok()
      }
      if (verb === 'restart') {
        events.push(`restart ${args[args.length - 1]}`)
        return ok()
      }
      return ok()
    }
    if (command === 'python3' || command === 'python') {
      if (args[0] === '--version') return ok('Python 3.12.0')
      events.push('provision.py')
      return ok()
    }
    return { status: 127, stdout: '', stderr: `no ${command}` }
  }

  const http = async (method: string, url: string, { body, token }: { body?: unknown; token?: string } = {}) => {
    const reply = (status: number, json: unknown = {}) => ({ status, json })
    if (!world.running) return reply(0, null)
    if (url.startsWith(login)) return reply(200)
    if (!url.startsWith(issuer)) return reply(404)
    const path = url.slice(issuer.length)
    if (path === '/.well-known/openid-configuration') return reply(200, { issuer })
    const who = token ? world.tokens.get(token) : undefined
    if (!who || who.expires < NOW.toISOString()) return reply(401)
    if (path === '/admin/v1/instances/me') {
      return world.failInstanceRead ? reply(500) : reply(200, { instance: { id: world.runningInstanceId } })
    }
    if (path === '/auth/v1/users/me') return reply(200, { user: { id: who.userId } })
    if (path === '/management/v1/users/_search') return reply(200, { result: [{ id: 'login-client-user' }] })
    const pats = /^\/management\/v1\/users\/([^/]+)\/pats(?:\/(_search|[^/]+))?$/.exec(path)
    if (pats) {
      const [, userId, tail] = pats
      if (method === 'POST' && tail === '_search') {
        const result = [...world.tokens.values()].filter((t) => t.userId === userId).map((t) => ({ id: t.id, expirationDate: t.expires }))
        return reply(200, { result })
      }
      if (method === 'POST' && tail === undefined) {
        const expires = (body as { expirationDate: string }).expirationDate
        const fresh = issueToken(userId, expires)
        return reply(200, { tokenId: world.tokens.get(fresh)!.id, token: fresh })
      }
      if (method === 'DELETE') {
        for (const [key, value] of world.tokens) if (value.id === tail && value.userId === userId) world.tokens.delete(key)
        events.push(`delete ${tail}`)
        return reply(200)
      }
    }
    return reply(404)
  }

  const deps = {
    env: { ...process.env, KORAS_HOME: koras, KORAS_ESCROW_BACKUP_DIR: backupDir, KORAS_ZITADEL_MODE: '' },
    platform: process.platform,
    now: () => NOW,
    exec,
    gpgExec: undefined,
    http,
    sleep: async () => {},
    log: (line: string) => logs.push(line),
    root,
    home: OTHER_VOLUME ?? koras,
    randomInt: undefined,
    uid: typeof process.getuid === 'function' ? process.getuid() : null,
    gid: typeof process.getgid === 'function' ? process.getgid() : null,
  }
  const machineId = `${hostname().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30) || 'machine'}`
  return { deps, doppler, events, calls, logs, world, koras, backupDir, issuer, login, machineId }
}

function clean(root: string) {
  for (const rel of ['local/zitadel/machinekey/pat', 'local/zitadel/bootstrap/login-client.pat']) {
    rmSync(join(root, rel), { force: true })
  }
}

/** Every value compose was ever handed, flattened, to search for a secret. */
function everythingComposeSaw(calls: Call[]): string {
  return calls
    .filter((c) => c.command === 'docker')
    .map((c) => [...c.args, ...Object.values(c.env ?? {})].join('\n'))
    .join('\n')
}

// ── Rendered output (T-U1 to T-U7, T-U15 to T-U17) ───────────────────────────

const COMBINATIONS: Array<[ProfileName, string, { with?: string[]; without?: string[] }]> = [
  ['product', 'zs-product', {}],
  ['product', 'zs-product-full', { with: ['marketing', 'ai_gateway', 'scheduler'] }],
  ['product', 'zs-product-lean', { without: ['admin', 'worker'] }],
  ['control-plane', 'zs-cp', {}],
]

describe.each(COMBINATIONS)('%s (%s): rendered local ZITADEL', (profile, slug, overrides) => {
  let gen: Awaited<ReturnType<typeof generate>>
  let base: string
  let init: string
  let legacy: string

  beforeAll(async () => {
    gen = await generate(profile, slug, overrides)
    base = gen.read('local/docker-compose.yml')
    init = gen.read('local/docker-compose.init.yml')
    legacy = gen.read('local/docker-compose.legacy-zitadel.yml')
  })

  const uncommented = (text: string) =>
    text
      .split('\n')
      .filter((line) => !/^\s*#/.test(line))
      .join('\n')

  it('T-U1: the base file can start ZITADEL but never create one, and holds no key', () => {
    const body = uncommented(base)
    expect(body).not.toContain(PLACEHOLDER)
    expect(body).not.toContain('masterkeyFromEnv')
    expect(body).not.toContain('start-from-init')
    expect(body).not.toContain('ZITADEL_FIRSTINSTANCE_')
    expect(body).not.toMatch(/ZITADEL_MASTERKEY\s*:/)
  })

  it('T-U2: the key is a file secret behind a fail-closed guard, passed with --masterkeyFile only', () => {
    expect(base).toMatch(/^secrets:\n {2}zitadel_masterkey:\n {4}file: \$\{KORAS_ZITADEL_MASTERKEY_FILE:\?[^}]+\}$/m)
    expect(base).toMatch(/^ {4}command: start --masterkeyFile \/run\/secrets\/zitadel_masterkey --tlsMode disabled$/m)
    expect(base).toMatch(/^ {4}user: "\$\{KORAS_ZITADEL_USER:\?[^}]+\}"$/m)
    expect(base).toMatch(/^ {4}user: "\$\{KORAS_ZITADEL_LOGIN_USER:\?[^}]+\}"$/m)
  })

  it('T-U3: the placeholder occurs in exactly one rendered file, the legacy override', () => {
    const holders = gen.fileList.filter((file) => {
      if (/\.(png|ico|woff2?|zip|jpg)$/.test(file)) return false
      return gen.read(file).includes(PLACEHOLDER)
    })
    expect(holders).toEqual(['local/docker-compose.legacy-zitadel.yml'])
  })

  it('T-U4: every ZITADEL and login port is published on loopback only', () => {
    const services = ['zitadel', 'zitadel-login']
    for (const service of services) {
      const block = new RegExp(`^ {2}${service}:\\n((?: {4}.*\\n|\\n)+)`, 'm').exec(base)?.[1] ?? ''
      const ports = (/^ {4}ports:\n((?: {6}(?:- |#).*\n)+)/m.exec(block)?.[1] ?? '')
        .split('\n')
        .filter((line) => line.startsWith('      - '))
      expect(ports, service).not.toEqual([])
      for (const line of ports) expect(line, service).toMatch(/^ {6}- "127\.0\.0\.1:/)
    }
  })

  it('T-U5: the login container is pinned to the API tag, with every verified v4.17.1 setting', () => {
    const api = /image: ghcr\.io\/zitadel\/zitadel:(v[\d.]+)/.exec(base)?.[1]
    const login = /image: ghcr\.io\/zitadel\/zitadel-login:(v[\d.]+)/.exec(base)?.[1]
    expect(api).toBe('v4.17.1')
    expect(login).toBe(api)
    const pinned = [
      'ZITADEL_EXTERNALDOMAIN: localhost',
      'ZITADEL_EXTERNALSECURE: "false"',
      'ZITADEL_TLS_ENABLED: "false"',
      'ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED: "true"',
      'ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_BASEURI: http://localhost:${KORAS_PORT_ZITADEL_LOGIN:-',
      'ZITADEL_OIDC_DEFAULTLOGINURLV2: http://localhost:${KORAS_PORT_ZITADEL_LOGIN:-',
      'ZITADEL_OIDC_DEFAULTLOGOUTURLV2: http://localhost:${KORAS_PORT_ZITADEL_LOGIN:-',
      'ZITADEL_SAML_DEFAULTLOGINURLV2: http://localhost:${KORAS_PORT_ZITADEL_LOGIN:-',
      'ZITADEL_API_URL: http://zitadel:8080',
      'NEXT_PUBLIC_BASE_PATH: /ui/v2/login',
      'ZITADEL_SERVICE_USER_TOKEN_FILE: /zitadel/bootstrap/login-client.pat',
      'CUSTOM_REQUEST_HEADERS: Host:localhost,X-Forwarded-Proto:http',
      'node /app/healthcheck.mjs http://localhost:3000/ui/v2/login/healthy',
      'test: ["CMD", "/app/zitadel", "ready"]',
    ]
    for (const line of pinned) expect(base, line).toContain(line)
    expect(base).toMatch(/\/ui\/v2\/login\/login\?authRequest=$/m)
    expect(base).toMatch(/\/ui\/v2\/login\/logout\?post_logout_redirect=$/m)
    expect(base).toMatch(/\/ui\/v2\/login\/login\?samlRequest=$/m)
    for (const line of [
      'ZITADEL_FIRSTINSTANCE_LOGINCLIENTPATPATH: /zitadel/bootstrap/login-client.pat',
      'ZITADEL_FIRSTINSTANCE_ORG_LOGINCLIENT_MACHINE_USERNAME: login-client',
      'ZITADEL_FIRSTINSTANCE_ORG_LOGINCLIENT_MACHINE_NAME: Automatically Initialized IAM_LOGIN_CLIENT',
      'ZITADEL_FIRSTINSTANCE_PATPATH: /machinekey/pat',
    ]) {
      expect(init, line).toContain(line)
    }
  })

  it('T-U6: the legacy override starts, never initialises, and carries no login v2', () => {
    expect(legacy).toMatch(/^ {4}command: start --masterkeyFromEnv --tlsMode disabled$/m)
    expect(uncommented(legacy)).not.toContain('start-from-init')
    expect(uncommented(legacy)).not.toMatch(/LOGINV2|DEFAULTLOGINURLV2|DEFAULTLOGOUTURLV2/)
    expect(legacy).toMatch(/^ {2}zitadel-login:\n {4}profiles: \["legacy-recovery-excluded"\]$/m)
    expect(legacy).toMatch(/^ {4}secrets: !reset \[\]$/m)
    expect(legacy).toMatch(/^ {4}environment: !override$/m)
  })

  it('T-U6: the init override is the one place start-from-init and first-instance settings live', () => {
    expect(init).toMatch(/command: start-from-init --masterkeyFile \/run\/secrets\/zitadel_masterkey --steps \/run\/secrets\/zitadel_init_steps --tlsMode disabled/)
    expect(init).toMatch(/file: \$\{KORAS_ZITADEL_INIT_STEPS_FILE:\?[^}]+\}/)
    // The password is in the steps file, never in compose.
    expect(uncommented(init)).not.toMatch(/HUMAN_PASSWORD\s*:/)
  })

  it('T-U7: .env.local.example carries no masterkey', () => {
    const example = gen.fileList.includes('local/config/.env.local.example')
      ? gen.read('local/config/.env.local.example')
      : ''
    expect(example).not.toMatch(/^ZITADEL_MASTERKEY=/m)
    expect(example).not.toMatch(/^ZITADEL_ADMIN_PASSWORD=/m)
  })

  it('T-U15: no make or pnpm target starts compose except through stack.mjs', () => {
    const makefile = gen.read('Makefile')
    const scripts = Object.values(JSON.parse(gen.read('package.json')).scripts as Record<string, string>)
    const recipes = makefile.split('\n').filter((line) => line.startsWith('\t'))
    for (const line of [...recipes, ...scripts]) {
      expect(line).not.toMatch(/docker[ -]compose\b.*\bup\b/)
    }
    expect(makefile).toMatch(/^dev:.*\n\tbash \.\/local\/scripts\/preflight\.sh\n\tnode \.\/local\/scripts\/stack\.mjs up$/m)
    expect(JSON.parse(gen.read('package.json')).scripts['stack:up']).toBe('node local/scripts/stack.mjs up')
  })

  it('T-U16: no rendered file carries the default admin password', () => {
    const holders = gen.fileList.filter((file) => {
      if (/\.(png|ico|woff2?|zip|jpg)$/.test(file)) return false
      return gen.read(file).includes(DEFAULT_PASSWORD)
    })
    expect(holders).toEqual([])
  })

  it('T-U17: both access-token expiries come from one guarded value, never 2100 and never empty', () => {
    const expiries = [...init.matchAll(/PAT_EXPIRATIONDATE: (.*)$/gm)].map((m) => m[1])
    expect(expiries).toHaveLength(2)
    for (const value of expiries) expect(value).toMatch(/^\$\{KORAS_ZITADEL_PAT_EXPIRES_AT:\?[^}]+\}$/)
    expect(base + init).not.toContain('2100-01-01')
  })

  it('ports: the login port is resolved and recorded like the issuer', () => {
    expect(gen.read('local/scripts/ports.sh')).toMatch(/^KORAS_PORT_ZITADEL_LOGIN \d+$/m)
  })

  it('ignores the login-client token directory', () => {
    expect(gen.read('local/zitadel/bootstrap/.gitignore')).toMatch(/^\*$/m)
  })

  it('provision.py sets login v2 on the application and refuses an unsafe instance', () => {
    const provision = gen.read('local/zitadel/provision.py')
    expect(provision).toContain('payload["loginVersion"] = {"loginV2": {"baseUri": LOGIN_URL}}')
    // Across whitespace: the constants are wrapped to fit ruff's line length.
    expect(provision).toMatch(new RegExp(`PLACEHOLDER_FINGERPRINT = \\(?\\s*"sha256:${sha256(PLACEHOLDER)}"`))
    expect(provision).toMatch(new RegExp(`DEFAULT_PASSWORD_FINGERPRINT = \\(?\\s*"sha256:${sha256(DEFAULT_PASSWORD)}"`))
    expect(provision).toMatch(/\.localhost\/api\/auth\/callback/)
  })
})

// ── Modules ──────────────────────────────────────────────────────────────────

describe('masterkey.mjs', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  let mk: Module

  beforeAll(async () => {
    gen = await generate('product', 'zs-masterkey')
    mk = await load(gen.root, 'local/zitadel/masterkey.mjs')
  })

  it('refuses the placeholder by fingerprint, which is the placeholder\'s', () => {
    expect(mk.PLACEHOLDER_FINGERPRINT).toBe(`sha256:${sha256(PLACEHOLDER)}`)
    expect(mk.isPlaceholder(PLACEHOLDER)).toBe(true)
    expect(() => mk.assertKeyShape(PLACEHOLDER)).toThrow(/placeholder/)
  })

  it('T-U8: 32 characters of [A-Za-z0-9], 1000 draws all distinct', () => {
    const seen = new Set<string>()
    for (let i = 0; i < 1000; i += 1) {
      const key = mk.generateKey()
      expect(key).toMatch(/^[A-Za-z0-9]{32}$/)
      seen.add(key)
    }
    expect(seen.size).toBe(1000)
  })

  it('T-U8: the generator asserts its own output', () => {
    // A broken source of randomness that always answers 0 still yields 32
    // valid characters; one answering past the charset yields `undefined`.
    expect(() => mk.generateKey(() => 99)).toThrow(/A-Za-z0-9|exactly 32/)
  })

  it('T-U8: the cache file is exactly 32 bytes, with no newline, and never overwritten', () => {
    const dir = mkdtempSync(join(OUT, 'mk-'))
    const file = join(dir, 'secrets', 'zitadel-masterkey')
    const key = mk.generateKey()
    mk.writeSecretFile(file, key)
    expect(statSync(file).size).toBe(32)
    expect(readFileSync(file)).toEqual(Buffer.from(key))
    expect(() => mk.writeSecretFile(file, mk.generateKey())).toThrow(/never overwritten/)
    expect(readFileSync(file, 'utf8')).toBe(key)
  })

  it.skipIf(process.platform === 'win32')('T-U9: POSIX file 0600, directory 0700, owned by this user', () => {
    const dir = mkdtempSync(join(OUT, 'mk-posix-'))
    const file = join(dir, 'nested', 'zitadel-admin-password')
    mk.writeSecretFile(file, 'synthetic-secret')
    expect(statSync(file).mode & 0o777).toBe(0o600)
    expect(statSync(join(dir, 'nested')).mode & 0o777).toBe(0o700)
    chmodSync(file, 0o644)
    expect(() => mk.verifySecretFile(file)).toThrow(/mode 644/)
    chmodSync(file, 0o600)
    chmodSync(join(dir, 'nested'), 0o755)
    expect(() => mk.verifySecretFile(file)).toThrow(/expected 700/)
  })

  it.skipIf(process.platform !== 'win32')('T-U9: Windows ACL holds exactly one principal, this user', () => {
    const dir = mkdtempSync(join(OUT, 'mk-acl-'))
    const file = join(dir, 'zitadel-masterkey')
    mk.writeSecretFile(file, mk.generateKey())
    const listing = spawnSync('icacls', [file], { encoding: 'utf8' }).stdout
    const entries = mk.parseIcacls(listing, file)
    expect(entries).toHaveLength(1)
    expect(entries[0].toLowerCase()).toContain((process.env.USERNAME ?? '').toLowerCase())
    // Everyone (S-1-1-0) granted read: refused.
    spawnSync('icacls', [file, '/grant', '*S-1-1-0:R'])
    expect(() => mk.verifySecretFile(file)).toThrow(/more than its owner/)
  })

  it('T-U10: read refuses a missing file, with no fallback', () => {
    expect(() => mk.readKey(join(OUT, 'no-such-key'))).toThrow(/missing/)
    try {
      mk.readKey(join(OUT, 'no-such-key'))
    } catch (error) {
      expect((error as { code: string }).code).toBe('KEY_MISSING')
      expect((error as { hint: string }).hint).toMatch(/Nothing falls back/)
    }
  })

  it('T-U10: read refuses a wrong size, the placeholder, and a fingerprint mismatch', () => {
    const dir = mkdtempSync(join(OUT, 'mk-read-'))
    const newline = join(dir, 'newline', 'k')
    mk.writeSecretFile(newline, mk.generateKey() + '\n')
    expect(() => mk.readKey(newline)).toThrow(/33 bytes, not 32/)

    const placeholder = join(dir, 'placeholder', 'k')
    mk.writeSecretFile(placeholder, PLACEHOLDER)
    expect(() => mk.readKey(placeholder)).toThrow(/placeholder/)

    const key = mk.generateKey()
    const good = join(dir, 'good', 'k')
    mk.writeSecretFile(good, key)
    expect(mk.readKey(good, { expectedFingerprint: mk.fingerprint(key) })).toBe(key)
    expect(() => mk.readKey(good, { expectedFingerprint: mk.fingerprint(mk.generateKey()) })).toThrow(/not the one this instance was created with/)
  })

  it.skipIf(process.platform === 'win32')('T-U10: read refuses a key others can read', () => {
    const dir = mkdtempSync(join(OUT, 'mk-perm-'))
    const file = join(dir, 'k', 'zitadel-masterkey')
    mk.writeSecretFile(file, mk.generateKey())
    chmodSync(file, 0o640)
    expect(() => mk.readKey(file)).toThrow(/expected 600/)
  })
})

describe('state.mjs (T-U11)', () => {
  let st: Module
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('product', 'zs-state')
    st = await load(gen.root, 'local/zitadel/state.mjs')
  })

  const secure = () =>
    st.newSecureState({
      product: 'p',
      composeProject: 'p',
      issuer: 'http://localhost:18080',
      loginBaseUri: 'http://localhost:18081/ui/v2/login/',
      masterkeyFingerprint: `sha256:${'a'.repeat(64)}`,
      passwordFingerprint: `sha256:${'b'.repeat(64)}`,
      dopplerConfig: 'dev_local_box-a1b2c3',
      zitadelVersion: 'v4.17.1',
      now: NOW,
    })

  it('accepts a new secure and a new legacy state', () => {
    expect(st.validateState(secure())).toEqual([])
    expect(
      st.validateState(st.newLegacyState({ product: 'p', composeProject: 'p', issuer: 'http://localhost:8083', instanceId: '391918698199253000', zitadelVersion: 'v4.17.1', now: NOW })),
    ).toEqual([])
  })

  it('refuses schema v1, an unknown mode, and "escrowed" with a leg pending', () => {
    expect(st.validateState({ ...secure(), schemaVersion: 1 })[0]).toMatch(/expected 2/)
    expect(st.validateState({ ...secure(), mode: 'insecure' }).join()).toMatch(/mode/)
    const lying = secure()
    lying.escrow.status = 'escrowed'
    lying.escrow.doppler.status = 'done'
    expect(st.validateState(lying).join()).toMatch(/escrowed but a leg is pending/)
  })

  it('settles escrow from its legs, and only both legs make it escrowed', () => {
    const one = secure()
    one.escrow.doppler.status = 'done'
    expect(st.settleEscrow(one).escrow.status).toBe('unescrowed')
    one.escrow.backup.status = 'done'
    expect(st.settleEscrow(one).escrow.status).toBe('escrowed')
  })

  it('writes atomically, never writes an invalid state, and reads back what it wrote', () => {
    const dir = mkdtempSync(join(OUT, 'state-'))
    const file = join(dir, 'zitadel.json')
    st.writeState(file, secure())
    expect(st.readState(file)).toEqual(secure())
    expect(() => st.writeState(file, { ...secure(), mode: 'nope' })).toThrow(/invalid/)
    expect(st.readState(file).mode).toBe('secure')
    expect(readdirSync(dir)).toEqual(['zitadel.json'])
    writeFileSync(file, JSON.stringify({ ...secure(), schemaVersion: 1 }))
    expect(() => st.readState(file)).toThrow(/not valid/)
  })
})

describe('credentials.mjs', () => {
  let cr: Module
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('product', 'zs-credentials')
    cr = await load(gen.root, 'local/zitadel/credentials.mjs')
  })

  it('T-U16: generated passwords meet the policy, use the allowed symbols, and are never the default', () => {
    expect(cr.DEFAULT_PASSWORD_FINGERPRINT).toBe(`sha256:${sha256(DEFAULT_PASSWORD)}`)
    const seen = new Set<string>()
    for (let i = 0; i < 1000; i += 1) {
      const password = cr.generatePassword()
      expect(password).toHaveLength(24)
      expect(cr.satisfiesPolicy(password)).toBe(true)
      expect(password).toMatch(/^[A-Za-z0-9!%*+\-.:=?@^_~]+$/)
      expect(password).not.toBe(DEFAULT_PASSWORD)
      seen.add(password)
    }
    expect(seen.size).toBe(1000)
    expect(() => cr.assertPassword(DEFAULT_PASSWORD)).toThrow(/default/)
  })

  it('T-U16: the steps file carries the generated password, single-quoted, and refuses the default', () => {
    const password = cr.generatePassword()
    const steps = cr.renderInitSteps({ adminPassword: password })
    expect(steps).toContain(`      Password: '${password}'`)
    expect(steps).toContain('PasswordChangeRequired: false')
    expect(() => cr.renderInitSteps({ adminPassword: DEFAULT_PASSWORD })).toThrow(/default/)
  })

  it('T-U17: an access token expires provision time + 365 days, in ZITADEL\'s form', () => {
    const expiry = cr.patExpiry(NOW)
    expect(expiry).toBe('2027-10-09T12:00:00Z')
    expect(expiry).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
  })

  it('warns inside 30 days and marks an expired machine token for refusal', () => {
    const soon = cr.patHealth({ machine: { expiresAt: '2026-10-20T00:00:00Z' }, loginClient: { expiresAt: '2027-10-09T00:00:00Z' } }, NOW)
    expect(soon.expired).toBeNull()
    expect(soon.warnings.join()).toMatch(/machine access token expires in 11 day/)
    const gone = cr.patHealth({ machine: { expiresAt: '2026-10-01T00:00:00Z' }, loginClient: { expiresAt: null } }, NOW)
    expect(gone.expired).toBe('machine')
  })

  it('secureDelete zeroes and removes the file', () => {
    const file = join(mkdtempSync(join(OUT, 'sd-')), 'steps.yaml')
    writeFileSync(file, 'synthetic')
    cr.secureDelete(file)
    expect(existsSync(file)).toBe(false)
  })

  describe('T-U18: rotate-pat never leaves the instance without a working token', () => {
    function harness(fail: 'create' | 'verify' | 'consumer' | 'delete' | null) {
      const order: string[] = []
      const file = join(mkdtempSync(join(OUT, 'rot-')), 'pat')
      writeFileSync(file, 'old-token')
      const api = async (method: string, path: string, _body: unknown, token: string) => {
        order.push(`${method} ${path} as ${token}`)
        if (method === 'POST') return fail === 'create' ? { status: 500, json: null } : { status: 200, json: { tokenId: 'new-id', token: 'new-token' } }
        if (method === 'GET') return fail === 'verify' ? { status: 401, json: null } : { status: 200, json: { user: { id: 'user-1' } } }
        return fail === 'delete' ? { status: 500, json: null } : { status: 200, json: {} }
      }
      const run = () =>
        cr.rotatePat({
          which: 'machine',
          userId: 'user-1',
          oldTokenId: 'old-id',
          adminToken: 'old-token',
          deleteWithNewToken: true,
          tokenFile: file,
          readTokenFile: (f: string) => readFileSync(f, 'utf8'),
          writeToken: (f: string, t: string) => {
            order.push(`write ${t}`)
            writeFileSync(f, t)
          },
          api,
          now: NOW,
          verifyConsumer: async () => {
            if (fail === 'consumer') throw new Error('login unhealthy')
          },
        })
      return { order, file, run }
    }

    it('deletes the old token only after the new one is written and verified', async () => {
      const { order, file, run } = harness(null)
      const result = await run()
      expect(result).toEqual({ tokenId: 'new-id', expiresAt: '2027-10-09T12:00:00Z', leftover: null })
      const write = order.indexOf('write new-token')
      const verify = order.findIndex((o) => o.startsWith('GET /auth/v1/users/me as new-token'))
      const remove = order.findIndex((o) => o.startsWith('DELETE'))
      expect(write).toBeGreaterThan(-1)
      expect(verify).toBeGreaterThan(write)
      expect(remove).toBeGreaterThan(verify)
      expect(order[remove]).toBe('DELETE /management/v1/users/user-1/pats/old-id as new-token')
      expect(readFileSync(file, 'utf8')).toBe('new-token')
    })

    for (const failure of ['create', 'verify', 'consumer'] as const) {
      it(`leaves the old file and token when ${failure} fails`, async () => {
        const { order, file, run } = harness(failure)
        await expect(run()).rejects.toThrow()
        expect(readFileSync(file, 'utf8')).toBe('old-token')
        expect(order.some((o) => o.startsWith('DELETE'))).toBe(false)
      })
    }

    it('reports, and does not hide, an old token it could not delete', async () => {
      const { run } = harness('delete')
      expect((await run()).leftover).toBe('old-id')
    })

    it('refuses without a recorded token id rather than guessing', async () => {
      await expect(
        cr.rotatePat({ which: 'machine', userId: 'u', oldTokenId: null, adminToken: 't', tokenFile: 'x', readTokenFile: () => '', writeToken: () => {}, api: async () => ({}), now: NOW }),
      ).rejects.toThrow(/No token id is recorded/)
    })
  })
})

describe('escrow leg 1: Doppler, write-once (T-E1)', () => {
  let ed: Module
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('product', 'zs-doppler')
    ed = await load(gen.root, 'local/zitadel/escrow-doppler.mjs')
  })

  it('writes and reads back, then a second escrow of the same key is a no-op', () => {
    const estate = fakeEstate(gen.root, { dopplerConfigs: ['dev_local_box-a1b2c3'] })
    const args = { project: 'zs-doppler', config: 'dev_local_box-a1b2c3', name: 'ZITADEL_MASTERKEY', exec: estate.deps.exec }
    expect(ed.escrowSecret({ ...args, value: 'synthetic-key-one' })).toBe('written')
    expect(ed.escrowSecret({ ...args, value: 'synthetic-key-one' })).toBe('unchanged')
    expect(estate.events.filter((e) => e.startsWith('doppler set'))).toHaveLength(1)
  })

  it('refuses a different key and leaves Doppler unchanged', () => {
    const estate = fakeEstate(gen.root, { dopplerConfigs: ['dev_local_box-a1b2c3'] })
    const args = { project: 'zs-doppler', config: 'dev_local_box-a1b2c3', name: 'ZITADEL_MASTERKEY', exec: estate.deps.exec }
    ed.escrowSecret({ ...args, value: 'synthetic-key-one' })
    expect(() => ed.escrowSecret({ ...args, value: 'synthetic-key-two' })).toThrow(/already holds a different ZITADEL_MASTERKEY/)
    expect(estate.doppler.get('dev_local_box-a1b2c3')!.get('ZITADEL_MASTERKEY')).toBe('synthetic-key-one')
  })

  it('refuses every config but a per-machine dev_local_* branch', () => {
    const estate = fakeEstate(gen.root, { dopplerConfigs: ['dev', 'stg', 'prd', 'dev_feature'] })
    for (const config of ['dev', 'stg', 'prd', 'dev_feature', 'dev_local_']) {
      expect(() => ed.escrowSecret({ project: 'p', config, name: 'ZITADEL_MASTERKEY', value: 'v', exec: estate.deps.exec }), config).toThrow(/Refusing to escrow/)
    }
    expect(estate.events).toEqual([])
  })

  it('passes the value on stdin, never in argv', () => {
    const estate = fakeEstate(gen.root, { dopplerConfigs: ['dev_local_box-a1b2c3'] })
    ed.escrowSecret({ project: 'p', config: 'dev_local_box-a1b2c3', name: 'ZITADEL_MASTERKEY', value: 'synthetic-in-stdin', exec: estate.deps.exec })
    expect(estate.calls.flatMap((c) => c.args).join(' ')).not.toContain('synthetic-in-stdin')
  })
})

describe.skipIf(!gpgAvailable)('escrow leg 2: encrypted backup (T-U19, T-E3, T-E7)', () => {
  let eb: Module
  let gen: Awaited<ReturnType<typeof generate>>
  let recipient: Awaited<ReturnType<typeof syntheticRecipient>>
  let recipientPath: string
  const key = 'Synthetic0Key1For2Escrow3Tests45'

  beforeAll(async () => {
    gen = await generate('product', 'zs-backup')
    eb = await load(gen.root, 'local/zitadel/escrow-backup.mjs')
    recipient = await syntheticRecipient(gen.root)
    recipientPath = join(mkdtempSync(join(OUT, 'recipient-')), 'recovery-recipient.json')
    writeFileSync(recipientPath, JSON.stringify({ fingerprint: recipient.fingerprint, armoredPublicKey: recipient.armored }))
  }, 120_000)

  afterAll(() => recipient?.close())

  function leg(overrides: Record<string, unknown> = {}) {
    return eb.escrowBackup({
      key,
      keyFingerprint: `sha256:${sha256(key)}`,
      product: 'zs-backup',
      machineId: 'box-a1b2c3',
      recipientPath,
      backupDir: mkdtempSync(join(OUT, 'external-')),
      localDir: mkdtempSync(join(OUT, 'local-escrow-')),
      now: NOW,
      home: OTHER_VOLUME,
      ...overrides,
    })
  }

  it.skipIf(!OTHER_VOLUME)('writes a verified artifact in both places, holding no plaintext (T-E7)', () => {
    const result = leg()
    expect(result.status).toBe('done')
    expect(result.recipient).toBe(recipient.fingerprint)
    expect(result.paths).toHaveLength(2)
    for (const artifact of result.paths) {
      const bytes = readFileSync(artifact)
      expect(bytes.includes(Buffer.from(key))).toBe(false)
      expect(bytes.includes(Buffer.from(Buffer.from(key).toString('base64')))).toBe(false)
      const sidecar = readFileSync(`${artifact}.json`, 'utf8')
      expect(sidecar).not.toContain(key)
      expect(sidecar).not.toContain(Buffer.from(key).toString('base64'))
      expect(sha256(bytes)).toBe(result.sha256)
      const ids = eb.packetRecipients(artifact)
      expect(ids).toHaveLength(1)
    }
  })

  it.skipIf(!OTHER_VOLUME)('T-E3: decrypts only with the recovery private key, to the same key', () => {
    const result = leg()
    expect(recipient.decrypt(result.paths[1])).toBe(key)
    // This machine's keyring does not hold the recovery key.
    const style = eb.gpgPathStyle()
    const empty = mkdtempSync(join(tmpdir(), 'kzn-'))
    const elsewhere = spawnSync('gpg', ['--homedir', eb.toGpgPath(empty, style), '--batch', '--decrypt', eb.toGpgPath(result.paths[1], style)], { encoding: 'utf8' })
    spawnSync('gpgconf', ['--homedir', eb.toGpgPath(empty, style), '--kill', 'gpg-agent'])
    rmSync(empty, { recursive: true, force: true })
    expect(elsewhere.status).not.toBe(0)
  })

  it.skipIf(!OTHER_VOLUME)('is write-once: an existing artifact is verified and kept, a tampered one refused', () => {
    const localDir = mkdtempSync(join(OUT, 'local-once-'))
    const backupDir = mkdtempSync(join(OUT, 'external-once-'))
    const first = leg({ localDir, backupDir })
    const second = leg({ localDir, backupDir })
    expect(second.sha256).toBe(first.sha256)
    writeFileSync(first.paths[0], Buffer.concat([readFileSync(first.paths[0]), Buffer.from('x')]))
    expect(() => leg({ localDir, backupDir })).toThrow(/does not match the digest/)
  })

  it('T-U19: no recipient installed leaves the leg pending', () => {
    expect(leg({ recipientPath: join(OUT, 'absent.json') })).toMatchObject({ status: 'pending' })
  })

  it('T-U19: a recipient whose key is not the pinned one fails', () => {
    const wrong = join(mkdtempSync(join(OUT, 'wrong-')), 'r.json')
    writeFileSync(wrong, JSON.stringify({ fingerprint: 'A'.repeat(40), armoredPublicKey: recipient.armored }))
    expect(() => leg({ recipientPath: wrong })).toThrow(/not the pinned/)
  })

  it('T-U19: a backup directory on the profile volume, or none, leaves the leg pending', () => {
    const local = mkdtempSync(join(OUT, 'same-'))
    expect(leg({ home: tmpdir(), backupDir: local })).toMatchObject({ status: 'pending', reason: expect.stringMatching(/same volume/) })
    expect(leg({ backupDir: undefined })).toMatchObject({ status: 'pending', reason: expect.stringMatching(/not set/) })
  })

  it.skipIf(!OTHER_VOLUME)('T-U19: an existing external copy with different bytes fails, never done', () => {
    const backupDir = mkdtempSync(join(OUT, 'external-clash-'))
    const name = eb.artifactName({ product: 'zs-backup', machineId: 'box-a1b2c3', keyFingerprint: `sha256:${sha256(key)}` })
    writeFileSync(join(backupDir, name), 'something else')
    expect(() => leg({ backupDir })).toThrow(/exists with different contents/)
  })

  it('a second key in the recipient file, or a cert-only key, is refused', () => {
    const doubled = join(mkdtempSync(join(OUT, 'dbl-')), 'r.json')
    writeFileSync(doubled, JSON.stringify({ fingerprint: recipient.fingerprint, armoredPublicKey: 'not a key' }))
    expect(() => leg({ recipientPath: doubled })).toThrow(/armoredPublicKey/)
  })
})

// ── stack.mjs ────────────────────────────────────────────────────────────────

describe('stack.mjs: up decides before anything starts (T-U12)', () => {
  let stack: Module
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('product', 'zs-decide')
    stack = await load(gen.root, 'local/scripts/stack.mjs')
  })

  const ready = () => ({
    mode: 'secure',
    phase: 'ready',
    instanceId: '391000000000000001',
    issuer: 'http://localhost:18080',
    loginBaseUri: 'http://localhost:18081/ui/v2/login/',
    escrow: { status: 'escrowed', doppler: { status: 'done' }, backup: { status: 'done' } },
    pats: { machine: { expiresAt: '2027-10-09T12:00:00Z' }, loginClient: { expiresAt: '2027-10-09T12:00:00Z' } },
  })
  const input = (over: Record<string, unknown> = {}) => ({
    state: ready(),
    dbExists: true,
    modeEnv: '',
    key: { ok: true },
    ports: { zitadel: 18080, zitadelLogin: 18081 },
    now: NOW,
    ...over,
  })
  const code = (over: Record<string, unknown>) => stack.decideUp(input(over)).code

  it('passes a ready, escrowed instance whose key, ports and tokens are right', () => {
    expect(stack.decideUp(input())).toEqual({ ok: true, mode: 'secure', warnings: [] })
  })

  it('refuses every other row of the table', () => {
    expect(code({ state: null, dbExists: false })).toBe('NO_STATE')
    expect(code({ state: null, dbExists: true })).toBe('UNRECORDED_INSTANCE')
    expect(code({ state: { ...ready(), phase: 'provisioning' } })).toBe('PROVISIONING_INCOMPLETE')
    for (const leg of ['doppler', 'backup']) {
      const state = ready()
      ;(state.escrow as Record<string, unknown>)[leg] = { status: 'pending' }
      state.escrow.status = 'unescrowed'
      expect(code({ state })).toBe('UNESCROWED')
    }
    expect(code({ dbExists: false })).toBe('INSTANCE_DB_MISSING')
    expect(code({ ports: { zitadel: 18090, zitadelLogin: 18081 } })).toBe('PORT_MISMATCH')
    expect(code({ ports: { zitadel: 18080, zitadelLogin: 18091 } })).toBe('PORT_MISMATCH')
    expect(code({ key: { ok: false, error: { code: 'KEY_MISSING', message: 'm' } } })).toBe('KEY_MISSING')
    expect(code({ modeEnv: 'legacy-recovery' })).toBe('MODE_MISMATCH')
    expect(code({ state: { ...ready(), pats: { machine: { expiresAt: '2026-10-01T00:00:00Z' }, loginClient: { expiresAt: null } } } })).toBe('PAT_EXPIRED')
  })

  it('warns, and passes, inside thirty days of a token expiring', () => {
    const decision = stack.decideUp(input({ state: { ...ready(), pats: { machine: { expiresAt: '2026-10-25T00:00:00Z' }, loginClient: { expiresAt: '2027-10-09T00:00:00Z' } } } }))
    expect(decision.ok).toBe(true)
    expect(decision.warnings.join()).toMatch(/expires in 16 day/)
  })

  it('applies the two-key rule to a legacy instance', () => {
    const legacy = { ...ready(), mode: 'legacy-recovery', loginBaseUri: null, escrow: { status: 'n/a' } }
    expect(code({ state: legacy, modeEnv: '' })).toBe('LEGACY_TWO_KEY')
    expect(stack.decideUp(input({ state: legacy, modeEnv: 'legacy-recovery' })).ok).toBe(true)
  })

  it('never runs ZITADEL as root on Linux', () => {
    expect(() => stack.containerUsers({ platform: 'linux', uid: 0, gid: 0 })).toThrow(/root/)
    expect(stack.containerUsers({ platform: 'linux', uid: 1001, gid: 1001 })).toEqual({ zitadel: '1001:1001', login: '1001:1001' })
    expect(stack.containerUsers({ platform: 'win32', uid: null, gid: null })).toEqual({ zitadel: '1000:1000', login: '1001:65533' })
  })
})

describe('stack.mjs: provisioning against a fake estate', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  let stack: Module
  let recipient: Awaited<ReturnType<typeof syntheticRecipient>> | null = null

  beforeAll(async () => {
    gen = await generate('product', 'zs-flow')
    stack = await load(gen.root, 'local/scripts/stack.mjs')
    if (gpgAvailable) recipient = await syntheticRecipient(gen.root)
  }, 120_000)

  afterAll(() => recipient?.close())

  function online() {
    clean(gen.root)
    const estate = fakeEstate(gen.root)
    // The machine id is created on first provision; the per-machine Doppler
    // config must exist for it. Pre-create machine.json so the name is known.
    const id = 'box-a1b2c3'
    writeFileSync(join(estate.koras, 'machine.json'), JSON.stringify({ machineId: id }))
    estate.doppler.set(`dev_local_${id}`, new Map())
    if (recipient) {
      writeFileSync(join(estate.koras, 'recovery-recipient.json'), JSON.stringify({ fingerprint: recipient.fingerprint, armoredPublicKey: recipient.armored }))
    }
    return { ...estate, config: `dev_local_${id}` }
  }

  const canEscrow = gpgAvailable && OTHER_VOLUME !== null

  it('T-U13: refuses when a state file or a zitadel database already exists', async () => {
    const estate = online()
    estate.world.dbExists = true
    await expect(stack.provisionFresh(estate.deps)).rejects.toThrow(/zitadel database already exists/)
    expect(existsSync(join(estate.koras, 'secrets'))).toBe(false)

    const second = online()
    mkdirSync(join(second.koras, 'state', 'zs-flow'), { recursive: true })
    writeFileSync(join(second.koras, 'state', 'zs-flow', 'zitadel.json'), JSON.stringify((await load(gen.root, 'local/zitadel/state.mjs')).newLegacyState({ product: 'zs-flow', composeProject: 'zs-flow', issuer: 'http://localhost:18080', instanceId: '391918698199253000', zitadelVersion: 'v4.17.1', now: NOW })))
    await expect(stack.provisionFresh(second.deps)).rejects.toThrow(/already records a legacy-recovery instance/)
  })

  it('T-I8 (unit): with Doppler unreachable and no --offline, fails before generating anything', async () => {
    const estate = online()
    estate.doppler.clear()
    await expect(stack.provisionFresh(estate.deps)).rejects.toThrow(/nothing was generated/)
    expect(existsSync(join(estate.koras, 'secrets'))).toBe(false)
    expect(existsSync(join(estate.koras, 'state', 'zs-flow', 'zitadel.json'))).toBe(false)
    expect(estate.events).not.toContain('start-from-init')
  })

  it('T-I8 (unit): --offline creates an unescrowed instance; provision.py is not run and up refuses', async () => {
    const estate = online()
    estate.doppler.clear()
    const state = await stack.provisionFresh(estate.deps, { offline: true })
    expect(state.escrow.status).toBe('unescrowed')
    expect(state.phase).toBe('provisioning')
    expect(estate.events).toContain('start-from-init')
    expect(estate.events).not.toContain('provision.py')
    expect(estate.events[estate.events.length - 1]).toBe('stop')
    await expect(stack.up(estate.deps)).rejects.toThrow(/did not finish|not escrowed/)
  })

  it.skipIf(!canEscrow)('T-E2: both legs complete before start-from-init, and the instance is ready', async () => {
    const estate = online()
    const state = await stack.provisionFresh(estate.deps)
    const init = estate.events.indexOf('start-from-init')
    expect(estate.events.indexOf('doppler set ZITADEL_MASTERKEY')).toBeGreaterThan(-1)
    expect(estate.events.indexOf('doppler set ZITADEL_MASTERKEY')).toBeLessThan(init)
    expect(estate.events.indexOf('doppler set ZITADEL_ADMIN_PASSWORD')).toBeLessThan(init)
    const artifacts = readdirSync(join(estate.koras, 'escrow-backup')).filter((f) => f.endsWith('.gpg'))
    expect(artifacts).toHaveLength(1)
    expect(state.escrow.backup.status).toBe('done')
    expect(state.phase).toBe('ready')
    expect(state.instanceId).toBe(estate.world.instanceId)
    expect(estate.events).toContain('provision.py')
    expect(estate.events.indexOf('provision.py')).toBeGreaterThan(estate.events.lastIndexOf('start'))
    // Tokens recorded with the expiry the init env was given.
    expect(state.pats.machine.expiresAt).toBe('2027-10-09T12:00:00Z')
    expect(state.pats.loginClient.expiresAt).toBe('2027-10-09T12:00:00Z')
    expect(state.pats.machine.tokenId).toMatch(/^tok-/)
  })

  it.skipIf(!canEscrow)('T-I10 (unit): compose never sees the key or the password; the steps file is gone', async () => {
    const estate = online()
    await stack.provisionFresh(estate.deps)
    const secrets = join(estate.koras, 'secrets', 'zs-flow', 'dev')
    const key = readFileSync(join(secrets, 'zitadel-masterkey'), 'utf8')
    const password = readFileSync(join(secrets, 'zitadel-admin-password'), 'utf8')
    const seen = everythingComposeSaw(estate.calls)
    expect(seen).not.toContain(key)
    expect(seen).not.toContain(password)
    // The steps file existed for init, held the generated password, and is gone.
    expect(estate.world.stepsSeen).toContain(`Password: '${password}'`)
    expect(existsSync(join(secrets, 'zitadel-init-steps.yaml'))).toBe(false)
    expect(password).not.toBe(DEFAULT_PASSWORD)
    // Nothing secret landed in the repository tree.
    for (const rel of ['local/zitadel/machinekey', 'local/zitadel/bootstrap']) {
      for (const file of readdirSync(join(gen.root, rel))) {
        if (file === '.gitignore') continue
        expect(readFileSync(join(gen.root, rel, file), 'utf8')).not.toContain(key)
      }
    }
  })

  it.skipIf(!canEscrow)('interrupted provisioning is finished by --resume, never by --fresh', async () => {
    const estate = online()
    estate.world.failInstanceRead = true
    await expect(stack.provisionFresh(estate.deps)).rejects.toThrow(/new instance's id/)
    const statePath = join(estate.koras, 'state', 'zs-flow', 'zitadel.json')
    const interrupted = JSON.parse(readFileSync(statePath, 'utf8'))
    expect(interrupted.phase).toBe('provisioning')
    expect(interrupted.initCompletedAt).toBeNull()
    expect(interrupted.escrow.status).toBe('escrowed')
    // The steps file is deleted even though init failed.
    expect(existsSync(join(estate.koras, 'secrets', 'zs-flow', 'dev', 'zitadel-init-steps.yaml'))).toBe(false)

    await expect(stack.provisionFresh(estate.deps)).rejects.toMatchObject({
      code: 'STATE_EXISTS',
      hint: expect.stringMatching(/provision --resume/),
    })
    await expect(stack.up(estate.deps)).rejects.toThrow(/did not finish/)

    estate.world.failInstanceRead = false
    const finished = await stack.provisionResume(estate.deps)
    expect(finished.phase).toBe('ready')
    // The same key throughout: escrow did not run twice.
    expect(estate.events.filter((e) => e === 'doppler set ZITADEL_MASTERKEY')).toHaveLength(1)
    await expect(stack.provisionResume(estate.deps)).rejects.toThrow(/no secure instance being provisioned/)
  })

  it.skipIf(!canEscrow)('up starts a ready instance and stops ZITADEL when the running instance is not the recorded one (T-I9)', async () => {
    const estate = online()
    await stack.provisionFresh(estate.deps)
    estate.events.length = 0
    await stack.up(estate.deps)
    expect(estate.events).toEqual(['start'])

    estate.world.runningInstanceId = '999999999999999999'
    await expect(stack.up(estate.deps)).rejects.toThrow(/not the recorded/)
    expect(estate.events[estate.events.length - 1]).toBe('stop')
  })

  it.skipIf(!canEscrow)('T-I2 (unit) and recovery: a missing or placeholder key refuses up; recover is explicit', async () => {
    const estate = online()
    await stack.provisionFresh(estate.deps)
    const keyFile = join(estate.koras, 'secrets', 'zs-flow', 'dev', 'zitadel-masterkey')
    const key = readFileSync(keyFile, 'utf8')

    unlinkSync(keyFile)
    estate.events.length = 0
    await expect(stack.up(estate.deps)).rejects.toThrow(/masterkey cache .* is missing/)
    expect(estate.events).not.toContain('start')
    expect(existsSync(keyFile)).toBe(false)

    await stack.recover(estate.deps)
    expect(readFileSync(keyFile, 'utf8')).toBe(key)
    await stack.up(estate.deps)

    // The placeholder in the cache: refused before compose.
    unlinkSync(keyFile)
    const mk = await load(gen.root, 'local/zitadel/masterkey.mjs')
    mk.writeSecretFile(keyFile, PLACEHOLDER)
    estate.events.length = 0
    await expect(stack.up(estate.deps)).rejects.toThrow(/placeholder/)
    expect(estate.events).toEqual([])
  })

  it.skipIf(!canEscrow)('T-E3: recover --from-backup restores the key from leg 2 with the recovery private key', async () => {
    const estate = online()
    const state = await stack.provisionFresh(estate.deps)
    const keyFile = join(estate.koras, 'secrets', 'zs-flow', 'dev', 'zitadel-masterkey')
    const key = readFileSync(keyFile, 'utf8')
    unlinkSync(keyFile)
    // The owner's keyring stands in for the offline recovery machine.
    const backup = await load(gen.root, 'local/zitadel/escrow-backup.mjs')
    const style = backup.gpgPathStyle()
    const owner = (command: string, args: string[], options: Record<string, unknown> = {}) =>
      spawnSync(command, command === 'gpg' && args[0] !== '--version' ? ['--homedir', backup.toGpgPath(recipient!.home, style), ...args] : args, { encoding: 'utf8', ...options })
    await stack.recover({ ...estate.deps, gpgExec: owner }, { fromBackup: state.escrow.backup.paths[1] })
    expect(readFileSync(keyFile, 'utf8')).toBe(key)
  })

  it.skipIf(!canEscrow)('escrow is idempotent, and records an off-machine copy without touching the artifact', async () => {
    const estate = online()
    const state = await stack.provisionFresh(estate.deps)
    const before = readFileSync(state.escrow.backup.paths[0])
    const again = await stack.escrow(estate.deps)
    expect(again.escrow.status).toBe('escrowed')
    expect(estate.events.filter((e) => e === 'doppler set ZITADEL_MASTERKEY')).toHaveLength(1)
    const recorded = await stack.escrow(estate.deps, { recordCopyLabel: 'owner-vault' })
    expect(recorded.escrow.backup.copies.map((c: { label: string }) => c.label)).toEqual(['owner-vault'])
    expect(readFileSync(state.escrow.backup.paths[0])).toEqual(before)
    const sidecar = JSON.parse(readFileSync(`${state.escrow.backup.paths[1]}.json`, 'utf8'))
    expect(sidecar.instanceId).toBe(estate.world.instanceId)
    expect(sidecar.copies.map((c: { label: string }) => c.label)).toEqual(['owner-vault'])
  })

  it.skipIf(!canEscrow)('T-I14 (unit): rotate-pat all replaces both tokens and deletes the old ones', async () => {
    const estate = online()
    const state = await stack.provisionFresh(estate.deps)
    const oldMachine = state.pats.machine.tokenId
    const oldLogin = state.pats.loginClient.tokenId
    const rotated = await stack.rotate(estate.deps, 'all')
    expect(rotated.pats.machine.tokenId).not.toBe(oldMachine)
    expect(rotated.pats.loginClient.tokenId).not.toBe(oldLogin)
    expect(estate.events).toContain(`delete ${oldMachine}`)
    expect(estate.events).toContain(`delete ${oldLogin}`)
    expect(estate.events).toContain('restart zitadel-login')
    // The old machine token no longer authenticates; the new one does.
    const fresh = readFileSync(join(gen.root, 'local', 'zitadel', 'machinekey', 'pat'), 'utf8')
    expect((await estate.deps.http('GET', `${estate.issuer}/auth/v1/users/me`, { token: fresh })).status).toBe(200)
    expect([...estate.world.tokens.values()].map((t) => t.id)).not.toContain(oldMachine)
  })

  it('status --show-admin is the one place the password is printed', async () => {
    const estate = online()
    estate.doppler.clear()
    await stack.provisionFresh(estate.deps, { offline: true })
    estate.logs.length = 0
    stack.status(estate.deps)
    const password = readFileSync(join(estate.koras, 'secrets', 'zs-flow', 'dev', 'zitadel-admin-password'), 'utf8')
    expect(estate.logs.join('\n')).not.toContain(password)
    stack.status(estate.deps, { showAdmin: true })
    expect(estate.logs.join('\n')).toContain(`admin / ${password}`)
  })
})

describe('stack.mjs: legacy recovery (A4)', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  let stack: Module

  beforeAll(async () => {
    gen = await generate('product', 'zs-legacy')
    stack = await load(gen.root, 'local/scripts/stack.mjs')
  })

  function adopted() {
    clean(gen.root)
    const estate = fakeEstate(gen.root)
    estate.world.dbExists = true
    estate.world.runningInstanceId = '391918698199253000'
    mkdirSync(join(gen.root, 'local', 'zitadel', 'machinekey'), { recursive: true })
    writeFileSync(join(gen.root, 'local', 'zitadel', 'machinekey', 'pat'), 'legacy-token')
    estate.world.tokens.set('legacy-token', { id: 'legacy', userId: 'machine-user', expires: '2100-01-01T00:00:00Z' })
    return estate
  }

  it('adopts by recording, starts nothing, and refuses to adopt twice', async () => {
    const estate = adopted()
    await stack.legacyAdopt(estate.deps, { instanceId: '391918698199253000', issuer: 'http://localhost:18080' })
    expect(estate.events).toEqual([])
    await expect(stack.legacyAdopt(estate.deps, { instanceId: '391918698199253000', issuer: 'http://localhost:18080' })).rejects.toThrow(/already exists/)
  })

  it('refuses an issuer off the resolved port', async () => {
    const estate = adopted()
    await expect(stack.legacyAdopt(estate.deps, { instanceId: '391918698199253000', issuer: 'http://localhost:9999' })).rejects.toThrow(/not on KORAS_PORT_ZITADEL/)
  })

  it('starts only with the second key, through the legacy override, pinned to the instance (T-I9)', async () => {
    const estate = adopted()
    await stack.legacyAdopt(estate.deps, { instanceId: '391918698199253000', issuer: 'http://localhost:18080' })
    await expect(stack.up(estate.deps)).rejects.toThrow(/legacy-recovery mode/)
    const legacyDeps = { ...estate.deps, env: { ...estate.deps.env, KORAS_ZITADEL_MODE: 'legacy-recovery' } }
    await stack.up(legacyDeps)
    expect(estate.events).toEqual(['start (legacy)'])
    // Never through the init override.
    expect(estate.calls.some((c) => c.args.some((a) => a.endsWith('docker-compose.init.yml')))).toBe(false)

    estate.world.runningInstanceId = '391000000000000999'
    await expect(stack.up(legacyDeps)).rejects.toThrow(/not the recorded 391918698199253000/)
    expect(estate.events[estate.events.length - 1]).toBe('stop')
  })

  it('has no rotation, and A14 leaves its credentials alone', async () => {
    const estate = adopted()
    await stack.legacyAdopt(estate.deps, { instanceId: '391918698199253000', issuer: 'http://localhost:18080', checkDefaultPassword: true })
    await expect(stack.rotate(estate.deps, 'all')).rejects.toThrow(/legacy instance keeps/)
    expect(estate.logs.join('\n')).toMatch(/not probed/)
  })
})

describe('stack.mjs: the compose passthrough and the inert environment', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  let stack: Module

  beforeAll(async () => {
    gen = await generate('product', 'zs-passthrough')
    stack = await load(gen.root, 'local/scripts/stack.mjs')
  })

  it('refuses up and down -v; allows stop', () => {
    const estate = fakeEstate(gen.root)
    expect(() => stack.composePassthrough(estate.deps, ['up', '-d'])).toThrow(/stack\.mjs up/)
    expect(() => stack.composePassthrough(estate.deps, ['down', '-v'])).toThrow(/make reset/)
    expect(() => stack.composePassthrough(estate.deps, ['down', '--volumes'])).toThrow(/make reset/)
    expect(stack.composePassthrough(estate.deps, ['stop'])).toBe(0)
  })

  it('exports a key path to an empty file, and no secret', () => {
    const estate = fakeEstate(gen.root)
    const exports = stack.inertExports(estate.deps)
    const keyFile = /KORAS_ZITADEL_MASTERKEY_FILE='([^']+)'/.exec(exports)?.[1] ?? ''
    expect(keyFile).toMatch(/zitadel-masterkey\.absent$/)
    expect(statSync(keyFile).size).toBe(0)
    expect(exports).not.toMatch(/ZITADEL_MASTERKEY=|PASSWORD/)
  })
})

describe('preflight.sh: unsafe local ZITADEL secrets are errors (spec §3.9)', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  const bash = spawnSync('bash', ['--version']).status === 0

  beforeAll(async () => {
    gen = await generate('product', 'zs-preflight')
  })

  function preflight(root: string, home: string) {
    return spawnSync('bash', [join(root, 'local/scripts/preflight.sh')], {
      cwd: root,
      encoding: 'utf8',
      env: { ...process.env, KORAS_HOME: home, PATH: process.env.PATH },
    })
  }

  it.skipIf(!bash)('errors, and exits 1, on an environment masterkey or a password in compose', () => {
    const root = join(OUT, 'pf-unsafe')
    mkdirSync(join(root, 'local', 'scripts'), { recursive: true })
    mkdirSync(join(root, 'local', 'zitadel'), { recursive: true })
    writeFileSync(join(root, 'local/scripts/preflight.sh'), gen.read('local/scripts/preflight.sh'))
    writeFileSync(
      join(root, 'local/docker-compose.yml'),
      `name: pf-unsafe\nservices:\n  zitadel:\n    command: start-from-init --masterkeyFromEnv\n    environment:\n      ZITADEL_MASTERKEY: x\n      ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD: y\n`,
    )
    const r = preflight(root, mkdtempSync(join(OUT, 'pf-home-')))
    expect(r.status).toBe(1)
    expect(r.stdout).toMatch(/ERROR local\/docker-compose\.yml starts ZITADEL on an environment masterkey/)
    expect(r.stdout).toMatch(/ERROR local\/docker-compose\.yml can initialise ZITADEL/)
    expect(r.stdout).toMatch(/ERROR local\/docker-compose\.yml sets a ZITADEL admin password/)
  })

  it.skipIf(!bash)('errors on a cached placeholder key or default password for a secure instance', async () => {
    const root = gen.root
    const home = mkdtempSync(join(OUT, 'pf-cache-'))
    const st = await load(root, 'local/zitadel/state.mjs')
    const mk = await load(root, 'local/zitadel/masterkey.mjs')
    const state = st.newSecureState({
      product: 'zs-preflight',
      composeProject: 'zs-preflight',
      issuer: 'http://localhost:18080',
      loginBaseUri: 'http://localhost:18081/ui/v2/login/',
      masterkeyFingerprint: `sha256:${sha256(PLACEHOLDER)}`,
      passwordFingerprint: `sha256:${sha256(DEFAULT_PASSWORD)}`,
      dopplerConfig: 'dev_local_box-a1b2c3',
      zitadelVersion: 'v4.17.1',
      now: NOW,
    })
    st.writeState(join(home, 'state', 'zs-preflight', 'zitadel.json'), state)
    mk.writeSecretFile(join(home, 'secrets', 'zs-preflight', 'dev', 'zitadel-masterkey'), PLACEHOLDER)
    mk.writeSecretFile(join(home, 'secrets', 'zs-preflight', 'dev', 'zitadel-admin-password'), DEFAULT_PASSWORD)
    const r = preflight(root, home)
    expect(r.status).toBe(1)
    expect(r.stdout).toMatch(/ERROR the cached ZITADEL masterkey is the public placeholder/)
    expect(r.stdout).toMatch(/ERROR the cached ZITADEL admin password is ZITADEL's default/)
    expect(r.stdout).toMatch(/not escrowed on both legs/)
    expect(r.stdout).not.toContain(PLACEHOLDER)
    expect(r.stdout).not.toContain(DEFAULT_PASSWORD)
  })
})

describe('provision.py refuses an unsafe instance', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  const python = ['python3', 'python'].find((p) => spawnSync(p, ['--version']).status === 0)

  beforeAll(async () => {
    gen = await generate('product', 'zs-provision-py')
  })

  function provision(statePath: string) {
    return spawnSync(python!, [join(gen.root, 'local/zitadel/provision.py')], {
      encoding: 'utf8',
      env: { ...process.env, ZITADEL_URL: 'http://localhost:1', KORAS_ZITADEL_STATE_FILE: statePath },
    })
  }

  it.skipIf(!python)('refuses with no state, an unescrowed instance, the placeholder key, and the default password', async () => {
    const st = await load(gen.root, 'local/zitadel/state.mjs')
    const dir = mkdtempSync(join(OUT, 'py-'))
    expect(provision(join(dir, 'absent.json')).stderr).toMatch(/No local ZITADEL instance is recorded/)

    const base = {
      product: 'p',
      composeProject: 'p',
      issuer: 'http://localhost:18080',
      loginBaseUri: 'http://localhost:18081/ui/v2/login/',
      masterkeyFingerprint: `sha256:${'a'.repeat(64)}`,
      passwordFingerprint: `sha256:${'b'.repeat(64)}`,
      dopplerConfig: 'dev_local_box-a1b2c3',
      zitadelVersion: 'v4.17.1',
      now: NOW,
    }
    const write = (state: unknown) => {
      const file = join(dir, `s-${Math.random().toString(16).slice(2)}.json`)
      writeFileSync(file, JSON.stringify(state))
      return file
    }
    expect(provision(write(st.newSecureState(base))).stderr).toMatch(/not escrowed/)
    const escrowed = (over: Record<string, unknown>) => {
      const s = st.newSecureState({ ...base, ...over })
      s.escrow = { ...s.escrow, status: 'escrowed', doppler: { ...s.escrow.doppler, status: 'done' }, backup: { ...s.escrow.backup, status: 'done' } }
      return s
    }
    expect(provision(write(escrowed({ masterkeyFingerprint: `sha256:${sha256(PLACEHOLDER)}` }))).stderr).toMatch(/placeholder masterkey/)
    expect(provision(write(escrowed({ passwordFingerprint: `sha256:${sha256(DEFAULT_PASSWORD)}` }))).stderr).toMatch(/default admin password/)
  })
})
