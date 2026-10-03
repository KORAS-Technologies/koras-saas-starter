import { describe, it, expect, beforeEach, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * The secret policy, run rather than read.
 *
 * Every case runs the real service-secrets.sh against a doppler and a flyctl
 * that record what they were asked and capture what was piped to them. What is
 * asserted is what reached the app, never what the script says it does -- a
 * test that read the script for the word "allowlist" would pass over a script
 * that imported everything.
 *
 * Every secret value in these cases is a sentinel, and every run, passing or
 * failing, is checked for those sentinels in its output.
 */

const SCRIPT = templatePath('_shared', 'local', 'scripts', 'service-secrets.sh')
const HARNESS = join(__dirname, 'service-secrets', 'harness.sh')

function has(bin: string, args: string[] = ['--version']): boolean {
  return spawnSync(bin, args, { shell: false }).status === 0
}
const yq = (() => {
  const r = spawnSync('yq', ['--version'], { encoding: 'utf8' })
  return r.status === 0 && /mikefarah/.test(r.stdout)
})()
const tools = has('bash') && has('jq') && yq

if (process.env.CI && !tools) {
  describe('service-secrets tooling', () => {
    it('needs bash, jq and mikefarah yq in CI', () => expect.fail('bash, jq and yq are required in CI'))
  })
}

const SENTINEL = {
  DB_URL: 'postgres://u:SENTINEL-db-password@h/db',
  API_KEY: 'SENTINEL-api-key-1',
  DB: 'SENTINEL-short-name-value',
  OTHER_TOKEN: 'SENTINEL-other-token',
  DOPPLER_PROJECT: 'SENTINEL-doppler-context',
}
const ALL_SENTINELS = Object.values(SENTINEL)

const doppler = (extra: Record<string, string> = {}) => JSON.stringify({ ...SENTINEL, ...extra })
const dotenv = () =>
  Object.entries(SENTINEL)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n') + '\n'

describe.skipIf(!tools)('service secret policy', () => {
  let dir: string
  let services: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'koras-secrets-'))
    services = join(dir, 'services')
    mkdirSync(join(services, 'svc'), { recursive: true })
  })
  afterAll(() => rmSync(dir, { recursive: true, force: true }))

  function descriptor(yaml: string | null) {
    if (yaml !== null) writeFileSync(join(services, 'svc', 'service.yaml'), yaml)
  }

  function run(
    mode: 'apply' | 'verify',
    opts: { dopplerJson?: string; dopplerEnv?: string; fly?: string[] } = {},
  ) {
    const calls = join(dir, 'calls.log')
    const imported = join(dir, 'imported.env')
    rmSync(calls, { force: true })
    rmSync(imported, { force: true })
    const args =
      mode === 'apply'
        ? ['apply', 'svc', 'p-svc-dev', 'proj', 'dev', services]
        : ['verify', 'svc', 'p-svc-dev', services]
    const r = spawnSync('bash', [HARNESS, ...args], {
      encoding: 'utf8',
      timeout: 60_000,
      env: {
        ...process.env,
        SCRIPT,
        CALLS: calls,
        IMPORTED: imported,
        FAKE_DOPPLER_JSON: opts.dopplerJson ?? doppler(),
        FAKE_DOPPLER_ENV: opts.dopplerEnv ?? dotenv(),
        FAKE_FLY_SECRETS: JSON.stringify((opts.fly ?? []).map((name) => ({ name, digest: 'd' }))),
      },
    })
    const log = existsSync(calls) ? readFileSync(calls, 'utf8').trim().split('\n').filter(Boolean) : []
    const out = existsSync(imported) ? readFileSync(imported, 'utf8') : null
    // Whatever happened, no secret value may be in anything a CI log would hold.
    for (const v of ALL_SENTINELS) {
      expect(r.stdout, 'stdout leaked a value').not.toContain(v)
      expect(r.stderr, 'stderr leaked a value').not.toContain(v)
      expect(log.join('\n'), 'a call line carried a value').not.toContain(v)
    }
    return { status: r.status, stdout: r.stdout, stderr: r.stderr, calls: log, imported: out }
  }

  const importedNames = (text: string | null) =>
    (text ?? '')
      .split('\n')
      .filter(Boolean)
      .map((l) => l.split('=')[0])
      .sort()

  describe('inherit', () => {
    it.each([
      ['no descriptor at all (the legacy case)', null],
      ['an explicit descriptor', 'schema_version: 1\nsecrets:\n  policy: inherit\n'],
      ['a descriptor that says nothing about secrets', 'schema_version: 1\nenvironments: [dev]\n'],
    ])('keeps the behaviour from before descriptors: %s', (_n, yaml) => {
      descriptor(yaml)
      const r = run('apply')
      expect(r.status).toBe(0)
      // Exactly the two commands the workflow ran before descriptors existed.
      expect(r.calls).toEqual([
        'doppler secrets download --no-file --format env-no-quotes --project proj --config dev',
        'flyctl secrets import --stage --app p-svc-dev',
      ])
      // DOPPLER_* is the CLI's own context and was always dropped; nothing else.
      expect(importedNames(r.imported)).toEqual(['API_KEY', 'DB', 'DB_URL', 'OTHER_TOKEN'])
    })

    it('verify has nothing to check and asks Fly nothing', () => {
      descriptor(null)
      const r = run('verify', { fly: ['ANYTHING'] })
      expect(r.status).toBe(0)
      expect(r.calls).toEqual([])
    })
  })

  describe('none', () => {
    beforeEach(() => descriptor('schema_version: 1\nsecrets:\n  policy: none\n'))

    it('imports nothing and never reads Doppler', () => {
      const r = run('apply')
      expect(r.status).toBe(0)
      expect(r.calls.some((c) => c.startsWith('doppler'))).toBe(false)
      expect(r.calls.some((c) => c.startsWith('flyctl secrets import'))).toBe(false)
      expect(r.imported).toBeNull()
    })

    it('passes when the app holds no secrets', () => {
      expect(run('apply', { fly: [] }).status).toBe(0)
      expect(run('verify', { fly: [] }).status).toBe(0)
    })

    it('FAILS, naming them, when the app already holds secrets -- and removes nothing', () => {
      for (const mode of ['apply', 'verify'] as const) {
        const r = run(mode, { fly: ['DB_URL', 'LEFTOVER'] })
        expect(r.status).not.toBe(0)
        expect(r.stderr).toContain('DB_URL')
        expect(r.stderr).toContain('LEFTOVER')
        expect(r.stderr).toContain('Nothing was removed')
        // The decision not to delete from a shared pipeline, asserted as an effect.
        expect(r.calls.some((c) => /secrets unset/.test(c))).toBe(false)
      }
    })

    it('says the same thing twice (idempotent)', () => {
      const a = run('verify', { fly: ['X'] })
      const b = run('verify', { fly: ['X'] })
      expect([a.status, a.stderr]).toEqual([b.status, b.stderr])
    })
  })

  describe('allowlist', () => {
    beforeEach(() =>
      descriptor('schema_version: 1\nsecrets:\n  policy: allowlist\n  allowlist: [DB_URL, API_KEY]\n'),
    )

    it('imports exactly the named secrets and nothing else', () => {
      const r = run('apply')
      expect(r.status).toBe(0)
      expect(importedNames(r.imported)).toEqual(['API_KEY', 'DB_URL'])
      expect(r.imported).toContain(`DB_URL=${SENTINEL.DB_URL}`)
      // Present in Doppler, not requested: must not arrive.
      for (const not of ['OTHER_TOKEN', 'DB=', 'DOPPLER_PROJECT']) {
        expect(r.imported).not.toContain(not)
      }
    })

    it('matches names exactly: DB does not pull in DB_URL', () => {
      descriptor('schema_version: 1\nsecrets:\n  policy: allowlist\n  allowlist: [DB]\n')
      const r = run('apply')
      expect(r.status).toBe(0)
      expect(importedNames(r.imported)).toEqual(['DB'])
    })

    it('fails when a requested secret is missing from Doppler, and imports nothing', () => {
      const r = run('apply', { dopplerJson: JSON.stringify({ DB_URL: SENTINEL.DB_URL }) })
      expect(r.status).not.toBe(0)
      expect(r.stderr).toContain('API_KEY')
      expect(r.imported).toBeNull()
    })

    it('fails when a requested secret is empty', () => {
      const r = run('apply', { dopplerJson: doppler({ API_KEY: '' }) })
      expect(r.status).not.toBe(0)
      expect(r.imported).toBeNull()
    })

    it.each([
      ['a line break', 'line1\nline2'],
      ['a leading quote', '"quoted'],
    ])('refuses a value that dotenv cannot carry: %s', (_n, value) => {
      const r = run('apply', { dopplerJson: doppler({ API_KEY: value }) })
      expect(r.status).not.toBe(0)
      expect(r.imported).toBeNull()
    })

    it('fails when the app already holds a secret outside the list', () => {
      const r = run('apply', { fly: ['DB_URL', 'STRAY'] })
      expect(r.status).not.toBe(0)
      expect(r.stderr).toContain('STRAY')
      expect(r.imported).toBeNull()
    })

    it('verify passes on a subset and fails on anything extra', () => {
      expect(run('verify', { fly: ['DB_URL'] }).status).toBe(0)
      expect(run('verify', { fly: ['DB_URL', 'API_KEY'] }).status).toBe(0)
      expect(run('verify', { fly: ['DB_URL', 'EXTRA'] }).status).not.toBe(0)
    })
  })

  describe('a descriptor that is wrong stops everything', () => {
    it.each([
      ['an unknown policy', 'schema_version: 1\nsecrets:\n  policy: everything\n'],
      ['an empty allowlist', 'schema_version: 1\nsecrets:\n  policy: allowlist\n  allowlist: []\n'],
      ['an allowlist with a pattern', 'schema_version: 1\nsecrets:\n  policy: allowlist\n  allowlist: ["DB_*"]\n'],
      ['a missing allowlist', 'schema_version: 1\nsecrets:\n  policy: allowlist\n'],
      ['an allowlist beside policy none', 'schema_version: 1\nsecrets:\n  policy: none\n  allowlist: [A]\n'],
      ['no policy', 'schema_version: 1\nsecrets: {}\n'],
      ['an unknown key', 'schema_version: 1\nsecrets:\n  policy: none\n  mode: strict\n'],
    ])('%s', (_n, yaml) => {
      descriptor(yaml)
      for (const mode of ['apply', 'verify'] as const) {
        const r = run(mode)
        expect(r.status).not.toBe(0)
        // Refused BEFORE touching either service: a bad descriptor must not
        // fall through to some default policy.
        expect(r.calls).toEqual([])
      }
    })
  })
})

describe('the scripts call each other through bash', () => {
  // A script checked out on Linux, or written by the generator, need not carry
  // the execute bit; calling a sibling directly then fails with status 126. That
  // is exactly how these failed in CI on their first run -- invisible on the
  // Windows machine they were written on, which has no execute bit to miss.
  it.each(['service-secrets.sh', 'verify-private-service.sh', 'register-with-control-plane.sh'])(
    '%s never executes a sibling script directly',
    (name) => {
      const lines = readFileSync(templatePath('_shared', 'local', 'scripts', name), 'utf8')
        .split('\n')
        .filter((l) => !l.trim().startsWith('#'))
      const direct = lines.filter((l) => /\$\(\s*"?\$(here|descriptor)\b|^\s*"?\$(here|descriptor)\b/.test(l))
      expect(direct, 'invoke siblings as `bash "$here/..."`').toEqual([])
    },
  )
})
