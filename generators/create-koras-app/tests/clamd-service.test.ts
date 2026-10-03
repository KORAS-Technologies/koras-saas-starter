import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { spawnSync } from 'node:child_process'
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
  utimesSync,
  chmodSync,
  readdirSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * The optional private malware scanner (clamd).
 *
 * Three kinds of assertion, kept apart on purpose:
 *
 *   - the CONTRACT: pinned image, limits derived from the 100 MiB ceiling,
 *     exposure. Read from the files, because that is where a person changes it.
 *   - the BEHAVIOUR of the entrypoint: when the scanner may say it is ready,
 *     and when it must refuse. Run, against stand-in daemons.
 *   - the REAL ENGINE, which this file cannot run without a container. That is
 *     tests/clamd-image.test.ts, opt-in, and the measurements it encodes are in
 *     docs/CLAMD_SERVICE.md.
 */

const DIR = (...p: string[]) => templatePath('product', 'services', 'clamd', ...p)
const read = (...p: string[]) => readFileSync(DIR(...p), 'utf8').replace(/\r\n/g, '\n')

/** A file with its comments removed, so a rule is asserted on what is in force. */
const code = (text: string) =>
  text
    .split('\n')
    .map((l) => l.replace(/\s+#.*$/, '').trimEnd())
    .filter((l) => l.trim() !== '' && !l.trim().startsWith('#'))

const MiB = 1024 * 1024
const size = (v: string): number => {
  const m = /^(\d+)([KMG]?)$/.exec(v)
  if (!m) throw new Error(`not a size: ${v}`)
  return Number(m[1]) * ({ '': 1, K: 1024, M: MiB, G: 1024 * MiB } as Record<string, number>)[m[2]]
}

/** Ratified 2026-10-03: the Phase-1 supported scan ceiling. */
const CEILING = 100 * MiB

function conf(): Map<string, string> {
  const out = new Map<string, string>()
  for (const line of code(read('clamd.conf'))) {
    const [k, ...rest] = line.trim().split(/\s+/)
    out.set(k, rest.join(' '))
  }
  return out
}

describe('the clamd image', () => {
  const docker = read('Dockerfile')

  it('is the official image, pinned by an explicit version AND an immutable digest', () => {
    const from = code(docker).filter((l) => l.startsWith('FROM '))
    expect(from).toHaveLength(1)
    expect(from[0]).toMatch(/^FROM clamav\/clamav:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$/)
  })

  it('floats nothing', () => {
    expect(docker.toLowerCase()).not.toMatch(/:latest|:stable|:\d+\.\d+(?!\.)\s/)
    expect(code(docker).join('\n')).not.toMatch(/clamav\/clamav(?!:\d+\.\d+\.\d+@sha256)/)
  })

  it('carries no product secret and nothing environment-specific', () => {
    const lines = code(docker)
    expect(lines.filter((l) => /^(ENV|ARG)\b/.test(l))).toEqual([])
    expect(lines.join('\n')).not.toMatch(/doppler|token|password|secret|api[_-]?key|\.env\b/i)
    // The only things copied in are the three files that are the same in every product.
    expect(lines.filter((l) => l.startsWith('COPY')).map((l) => l.split(/\s+/)[1])).toEqual([
      'services/clamd/clamd.conf',
      'services/clamd/freshclam.conf',
      'services/clamd/entrypoint.sh',
    ])
  })

  it('runs as the unprivileged user, with the shipped entrypoint as PID 1 under tini', () => {
    const lines = code(docker)
    expect(lines).toContain('USER clamav')
    expect(lines.find((l) => l.startsWith('ENTRYPOINT'))).toContain('/sbin/tini')
  })

  it('is the same bytes in every product: nothing in the template is rendered into it', () => {
    for (const f of ['Dockerfile', 'clamd.conf', 'freshclam.conf', 'entrypoint.sh', 'service.yaml']) {
      expect(read(f), f).not.toMatch(/\{\{/)
    }
  })
})

describe('the clamd limits, derived from a 100 MiB ceiling', () => {
  const c = conf()
  const get = (k: string) => c.get(k) ?? expect.fail(`${k} is not set`)

  it('accepts exactly the ceiling on the stream', () => {
    expect(size(get('StreamMaxLength'))).toBe(CEILING)
  })

  it('bounds total expansion at five times the ceiling', () => {
    expect(size(get('MaxScanSize'))).toBe(5 * CEILING)
  })

  it('sets MaxFileSize EQUAL to MaxScanSize, because anything lower is a silent hole', () => {
    // Measured on ClamAV 1.4.6 and 1.5.4 (docs/CLAMD_SERVICE.md): a ZIP entry
    // larger than MaxFileSize is skipped with NO alert, so with MaxFileSize at
    // the input ceiling a marker 120 MiB into an entry scanned clean. Equal to
    // MaxScanSize, an oversized entry exceeds MaxScanSize instead and alerts.
    expect(size(get('MaxFileSize'))).toBe(size(get('MaxScanSize')))
    // ...and the ceiling on what ARRIVES is the stream limit, not this one.
    expect(size(get('MaxFileSize'))).toBeGreaterThanOrEqual(size(get('StreamMaxLength')))
  })

  it('bounds nesting, file count and time', () => {
    expect(Number(get('MaxRecursion'))).toBe(8)
    expect(Number(get('MaxFiles'))).toBe(5000)
    expect(Number(get('MaxScanTime'))).toBe(120_000)
    // Tighter than ClamAV's own defaults (17, 10000): "bounded" has to mean
    // something. Ordinary Office documents need a small fraction of these.
    expect(Number(get('MaxRecursion'))).toBeLessThan(17)
    expect(Number(get('MaxFiles'))).toBeLessThan(10000)
  })

  it('never lets a limit hit or an unreadable file read as clean', () => {
    expect(get('AlertExceedsMax')).toBe('yes')
    expect(get('AlertEncrypted')).toBe('yes')
    expect(get('AlertEncryptedArchive')).toBe('yes')
    expect(get('AlertEncryptedDoc')).toBe('yes')
  })

  it('still inspects ordinary documents and archives', () => {
    for (const k of ['ScanArchive', 'ScanOLE2', 'ScanPDF', 'ScanXMLDOCS']) expect(get(k), k).toBe('yes')
  })

  it('fits two shared CPUs and 2 GiB: bounded threads, no doubled reload, exits on OOM', () => {
    expect(Number(get('MaxThreads'))).toBeLessThanOrEqual(2)
    // A reload briefly holds two copies of the signature set; that doubling is
    // what takes the machine over 2 GiB.
    expect(get('ConcurrentDatabaseReload')).toBe('no')
    expect(get('ExitOnOOM')).toBe('yes')
  })

  it('listens on TCP 3310 and nowhere else (no Unix socket, nothing bound by path)', () => {
    expect(get('TCPSocket')).toBe('3310')
    expect(c.has('LocalSocket')).toBe(false)
  })

  it('drops idle and slow clients', () => {
    for (const k of ['CommandReadTimeout', 'IdleTimeout', 'ReadTimeout']) expect(Number(get(k)), k).toBeGreaterThan(0)
  })
})

describe('the clamd fly.toml is private', () => {
  const toml = read('fly.toml.hbs').replace('{{flyRegion}}', 'iad')
  const lines = code(toml)
  const text = lines.join('\n')

  it('declares no HTTP service and no public service block', () => {
    expect(text).not.toMatch(/\[http_service/)
    expect(text).not.toMatch(/\[\[services/)
    expect(text).not.toMatch(/\[services/)
    expect(text).not.toMatch(/\[\[?http_service/)
  })

  it('opens no public port and names no public address, handler or domain', () => {
    expect(text).not.toMatch(/\bhandlers\b|\bforce_https\b|\bports\s*=|\[\[.*\.ports\]\]/)
    expect(text).not.toMatch(/\bip\b|ipv4|ipv6|anycast|flycast|dedicated|\bhostname\b/i)
  })

  it('has 2 GiB on shared-cpu-2x', () => {
    expect(text).toMatch(/cpu_kind = "shared"/)
    expect(text).toMatch(/cpus = 2\b/)
    expect(text).toMatch(/memory_mb = 2048\b/)
  })

  it('checks TCP 3310 as a machine check, not a service check', () => {
    expect(text).toMatch(/\[checks\.[a-z_]+\]/)
    expect(text).toMatch(/type = "tcp"/)
    expect(text).toMatch(/port = 3310\b/)
    // A service check needs a [[services]] block, which is the thing above.
    expect(text).not.toMatch(/tcp_checks/)
    // Long enough for a signature database to load on two shared CPUs.
    const grace = /grace_period = "(\d+)s"/.exec(text)
    expect(Number(grace?.[1])).toBeGreaterThanOrEqual(120)
  })

  it('restarts on failure, and gives up eventually', () => {
    expect(text).toMatch(/\[\[restart\]\]/)
    expect(text).toMatch(/policy = "on-failure"/)
    expect(text).toMatch(/retries = \d+/)
  })

  it('states the staleness limit the entrypoint enforces', () => {
    expect(text).toMatch(/CLAMD_MAX_DB_AGE_DAYS = "\d+"/)
  })

  it('declares itself dev-only, secret-free and private in its descriptor', () => {
    expect(code(read('service.yaml')).join('\n')).toBe(
      ['schema_version: 1', 'environments:', '  - dev', 'secrets:', '  policy: none', 'network: private'].join('\n'),
    )
  })
})

/**
 * When may the scanner say it is ready? Run against stand-in daemons that fail
 * on demand. The real engine's behaviour is the image test's business; this is
 * about the decisions the entrypoint takes around it.
 */
describe('the entrypoint decides readiness', () => {
  const sh = spawnSync('bash', ['--version']).status === 0
  const ENTRY = DIR('entrypoint.sh')
  let work: string
  let bin: string
  let db: string

  function stub(name: string, body: string) {
    writeFileSync(join(bin, name), `#!/usr/bin/env bash\n${body}\n`)
    chmodSync(join(bin, name), 0o755)
  }

  function seedDb(ageDays: number, parts = ['main.cvd', 'daily.cvd', 'bytecode.cvd']) {
    mkdirSync(db, { recursive: true })
    for (const p of parts) {
      const f = join(db, p)
      writeFileSync(f, 'x')
      const t = new Date(Date.now() - ageDays * 86400_000)
      utimesSync(f, t, t)
    }
  }

  beforeEach(() => {
    work = mkdtempSync(join(tmpdir(), 'koras-clamd-'))
    bin = join(work, 'bin')
    db = join(work, 'db')
    mkdirSync(bin, { recursive: true })
    mkdirSync(join(work, 'conf'), { recursive: true })
    // Defaults describe a healthy scanner; each case breaks one thing.
    stub('freshclam', 'for a in "$@"; do [ "$a" = "--daemon" ] && exec sleep 600; done; exit "${FAKE_FRESHCLAM_RC:-0}"')
    stub('clamd', 'if [ -n "${FAKE_CLAMD_DIES:-}" ]; then exit 3; fi; exec sleep 600')
    stub('nc', 'echo PONG')
    stub('clamdscan', 'echo "${FAKE_SCAN:-stream: Eicar-Test-Signature FOUND}"; exit 1')
  })
  afterEach(() => rmSync(work, { recursive: true, force: true }))

  /** Runs until it exits or `ms` passes; a still-running scanner is "ready and watching". */
  function run(env: Record<string, string> = {}, ms = 8000) {
    const r = spawnSync('bash', [ENTRY], {
      encoding: 'utf8',
      timeout: ms,
      env: {
        ...process.env,
        PATH: `${bin}${process.platform === 'win32' ? ';' : ':'}${process.env.PATH}`,
        CLAMD_CONF_DIR: join(work, 'conf'),
        CLAMD_DB_DIR: db,
        CLAMD_WATCH_INTERVAL: '1',
        ...env,
      },
    })
    const out = `${r.stdout}${r.stderr}`
    return { exited: r.signal === null && r.status !== null, status: r.status, out }
  }

  const stays = (r: { exited: boolean }) => expect(r.exited, 'it should still be running').toBe(false)

  it.skipIf(!sh)('is ready, and stays up, with a fresh database and a detecting scanner', () => {
    seedDb(0)
    const r = run()
    stays(r)
    expect(r.out).toContain('signature update succeeded')
    expect(r.out).toContain('ready: detection self-test passed')
  })

  it.skipIf(!sh)('refuses to start with no database at all', () => {
    mkdirSync(db, { recursive: true })
    const r = run()
    expect(r.status).toBe(1)
    expect(r.out).toContain('no usable signature database')
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('refuses to start with part of a database', () => {
    seedDb(0, ['main.cvd', 'daily.cvd']) // no bytecode
    const r = run()
    expect(r.status).toBe(1)
    expect(r.out).toContain('bytecode')
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('treats an empty database file as missing', () => {
    seedDb(0)
    writeFileSync(join(db, 'daily.cvd'), '')
    const r = run()
    expect(r.status).toBe(1)
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('continues on a fresh bundled database when the update fails, and says so', () => {
    seedDb(2)
    const r = run({ FAKE_FRESHCLAM_RC: '1' })
    stays(r)
    expect(r.out).toContain('WARNING: signature update failed')
    expect(r.out).toContain('2 day(s) old')
    expect(r.out).toContain('ready:')
  })

  it.skipIf(!sh)('refuses to start when the update fails and the database is too old', () => {
    seedDb(30)
    const r = run({ FAKE_FRESHCLAM_RC: '1' })
    expect(r.status).toBe(1)
    expect(r.out).toContain('refusing to start')
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('honours the configured staleness limit', () => {
    seedDb(3)
    expect(run({ FAKE_FRESHCLAM_RC: '1', CLAMD_MAX_DB_AGE_DAYS: '2' }).status).toBe(1)
    stays(run({ FAKE_FRESHCLAM_RC: '1', CLAMD_MAX_DB_AGE_DAYS: '5' }))
  })

  it.skipIf(!sh)('never advertises readiness when the self-test does not detect', () => {
    seedDb(0)
    const r = run({ FAKE_SCAN: 'stream: OK' })
    expect(r.status).toBe(1)
    expect(r.out).toContain('self-test did not detect')
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('exits if clamd dies during startup', () => {
    seedDb(0)
    stub('nc', 'exit 1') // never answers
    const r = run({ FAKE_CLAMD_DIES: '1' })
    expect(r.status).toBe(1)
    expect(r.out).toContain('clamd exited during startup')
    expect(r.out).not.toContain('ready:')
  })

  it.skipIf(!sh)('exits, rather than serve, when the database goes stale while running', () => {
    seedDb(2)
    // Update "succeeds" (so it starts) but nothing ever refreshes the files, so
    // after a second the watcher sees a database older than the limit.
    const r = run({ CLAMD_MAX_DB_AGE_DAYS: '1' }, 15000)
    expect(r.status).toBe(1)
    expect(r.out).toContain('day(s) old')
  })

  it('has the EICAR test string in no file, because every antivirus quarantines it', () => {
    for (const f of readdirSync(DIR())) {
      expect(read(f), f).not.toContain('EICAR-STANDARD-ANTIVIRUS-TEST-FILE')
    }
  })

  it('never reads or prints a secret', () => {
    const entry = code(read('entrypoint.sh')).join('\n')
    expect(entry).not.toMatch(/doppler|FLY_API_TOKEN|DOPPLER_TOKEN|secret/i)
  })
})
