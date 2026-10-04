import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { cpSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * The real ClamAV, in the real image, with the real configuration.
 *
 * Opt-in: `KORAS_CLAMD_IMAGE_TEST=1`. It needs Docker, pulls the pinned image
 * (about 100 MiB of signatures), starts it under the same 2 GiB / 2 CPU limit
 * the Fly machine has, and takes a few minutes. Everything the other clamd
 * tests can only read, this runs.
 *
 * Every expectation below is a measurement made on 2026-10-03 against ClamAV
 * 1.4.6 (and, where noted, 1.5.4); docs/CLAMD_SERVICE.md has the table. When
 * the pinned image is bumped, this is what says whether the limits still mean
 * what they did.
 */

const enabled = process.env.KORAS_CLAMD_IMAGE_TEST === '1'
const docker = spawnSync('docker', ['version'], { shell: false }).status === 0

const NAME = `koras-clamd-test-${process.pid}`
const TAG = `koras-clamd-image-test:${process.pid}`
const PROBE = join(__dirname, 'clamd', 'image_probe.py')
const MARKER = Buffer.from('KORAS-MARKER-0123456789')

let ctxDir: string
let results: Record<string, { answer: string; seconds: number }>

const d = (args: string[], opts: { timeout?: number } = {}) =>
  spawnSync('docker', args, { encoding: 'utf8', timeout: opts.timeout ?? 120_000, env: { ...process.env, MSYS_NO_PATHCONV: '1' } })

describe.skipIf(!enabled || !docker)('the real clamd image', () => {
  const logs = () => d(['logs', NAME]).stdout + d(['logs', NAME]).stderr

  beforeAll(() => {
    ctxDir = mkdtempSync(join(tmpdir(), 'koras-clamd-ctx-'))
    // The build context is the repository root of a generated project.
    mkdirSync(join(ctxDir, 'services'), { recursive: true })
    cpSync(templatePath('product', 'services', 'clamd'), join(ctxDir, 'services', 'clamd'), { recursive: true })
    const built = spawnSync('docker', ['build', '-q', '-f', 'services/clamd/Dockerfile', '-t', TAG, '.'], {
      cwd: ctxDir,
      encoding: 'utf8',
      timeout: 600_000,
    })
    expect(built.status, built.stderr).toBe(0)
    // The same ceiling the Fly machine has: shared-cpu-2x, 2 GiB.
    const run = d(['run', '-d', '--name', NAME, '--memory', '2g', '--cpus', '2', TAG])
    expect(run.status, run.stderr).toBe(0)
  }, 700_000)

  afterAll(() => {
    d(['rm', '-f', NAME])
    d(['rmi', '-f', TAG])
    if (ctxDir) rmSync(ctxDir, { recursive: true, force: true })
  })

  it('becomes ready only after loading signatures and passing its own detection test', () => {
    const deadline = Date.now() + 600_000
    let out = ''
    while (Date.now() < deadline) {
      out = logs()
      if (/ready: detection self-test passed|FATAL/.test(out)) break
      spawnSync('sleep', ['3'])
    }
    expect(out).toContain('signature update succeeded')
    expect(out).toContain('ready: detection self-test passed')
    expect(out).not.toContain('FATAL')
    // Ready is logged AFTER the engine reports the limits it loaded.
    expect(out.indexOf('Limits: ')).toBeGreaterThan(-1)
    expect(out.indexOf('Limits: ')).toBeLessThan(out.indexOf('ready:'))
  }, 700_000)

  it('runs as an unprivileged user and listens on TCP 3310 on IPv4 and IPv6, and nothing else', () => {
    expect(d(['exec', NAME, 'id', '-un']).stdout.trim()).toBe('clamav')
    const net = d(['exec', NAME, 'sh', '-c', 'netstat -tln']).stdout
    // IPv6 for Fly's private network; IPv4 because Fly's host-side machine
    // check connects to the machine's internal IPv4, not to loopback or 6PN.
    expect(net).toMatch(/:::3310\s.*LISTEN/)
    expect(net).toMatch(/0\.0\.0\.0:3310\s.*LISTEN/)
    expect(net.match(/:3310\s/g)).toHaveLength(2)
  })

  it('answers PING on loopback IPv4, the container IPv4 and IPv6', () => {
    const ping = (host: string) =>
      d(['exec', NAME, 'sh', '-c', `printf 'PING\n' | nc -w 2 ${host} 3310`]).stdout.trim()
    expect(ping('127.0.0.1')).toBe('PONG')
    expect(ping('$(hostname -i | cut -d" " -f1)')).toBe('PONG')
    expect(ping('::1')).toBe('PONG')
  })

  it('reports the limits it was configured with', () => {
    const out = logs()
    // The engine's own words for what it loaded, which are not the directive names.
    const grab = (label: string) => Number(new RegExp(`Limits: ${label} limit set to (\\d+)`).exec(out)?.[1])
    const MiB = 1024 * 1024
    expect(grab('Global size')).toBe(500 * MiB) // MaxScanSize
    expect(grab('File size')).toBe(500 * MiB) // MaxFileSize
    expect(grab('Recursion level')).toBe(8)
    expect(grab('Files')).toBe(5000)
    expect(grab('Global time')).toBe(120_000)
    expect(out).toContain('Alerting of encrypted archives _and_ documents enabled')
    expect(out).toContain('Heuristic alerting enabled for scans that exceed set maximums')
  })

  describe('against crafted inputs', () => {
    beforeAll(() => {
      // A one-line custom signature, loaded into THIS container only, so the
      // cases that need a payload at an arbitrary offset have something real
      // to find. (EICAR matches only at the start of a file.)
      const ndb = join(ctxDir, 'test.ndb')
      writeFileSync(ndb, `Koras.Test.Marker:0:*:${MARKER.toString('hex')}\n`)
      expect(d(['cp', ndb, `${NAME}:/var/lib/clamav/test.ndb`]).status).toBe(0)
      expect(d(['exec', '-u', 'root', NAME, 'chown', 'clamav:clamav', '/var/lib/clamav/test.ndb']).status).toBe(0)
      const reload = d([
        'run', '--rm', '--network', `container:${NAME}`, 'python:3.12-slim', 'python', '-c',
        "import socket;s=socket.create_connection(('::1',3310));s.sendall(b'zRELOAD\\0');print(s.recv(100))",
      ])
      expect(reload.stdout).toContain('RELOADING')

      const probe = spawnSync(
        'docker',
        ['run', '--rm', '--network', `container:${NAME}`, '-v', `${PROBE}:/probe.py:ro`, 'python:3.12-slim', 'python', '/probe.py'],
        { encoding: 'utf8', timeout: 1_800_000, env: { ...process.env, MSYS_NO_PATHCONV: '1' }, maxBuffer: 1 << 20 },
      )
      expect(probe.status, probe.stderr).toBe(0)
      results = JSON.parse(probe.stdout)
    }, 1_900_000)

    const a = (k: string) => results[k].answer

    it('accepts an ordinary Office-shaped document', () => expect(a('ordinary')).toBe('stream: OK'))
    it('accepts shallow nesting', () => expect(a('nested_ok')).toBe('stream: OK'))

    it('scans exactly the 100 MiB ceiling and refuses one byte more', () => {
      expect(a('exact_ceiling')).toBe('stream: OK')
      expect(a('over_ceiling')).toContain('INSTREAM size limit exceeded')
    })

    it('never reports encrypted content as clean', () => expect(a('encrypted')).toMatch(/Encrypted.*FOUND/))
    it('never reports too-deep nesting as clean', () => expect(a('nested_deep')).toContain('Limits.Exceeded.MaxRecursion'))
    it('never reports a file flood as clean', () => expect(a('flood')).toContain('Limits.Exceeded.MaxFiles'))

    it('never reports an oversized archive entry as clean (the 1 GiB bomb)', () => {
      expect(a('entry_1gib')).toContain('Limits.Exceeded.MaxScanSize')
      expect(a('entry_1gib')).toContain('FOUND')
    })
    it('never reports excess total expansion as clean', () => expect(a('many_60mib')).toContain('Limits.Exceeded.MaxScanSize'))

    it('FINDS a payload 120 MiB into an archive entry (it scanned clean when MaxFileSize was the ceiling)', () => {
      expect(a('hidden_40mib')).toContain('Koras.Test.Marker')
      expect(a('hidden_120mib')).toContain('Koras.Test.Marker')
    })

    it('bounds the time of every case', () => {
      for (const [name, r] of Object.entries(results)) {
        expect(r.seconds, name).toBeLessThan(120)
      }
    })

    it('KNOWN GAP (tripwire): a deflated, streamed, zip64 entry is not unpacked, and reads clean', () => {
      // Upstream, in 1.4.6 and 1.5.4 alike; no configuration reaches it. The
      // plain archive beside it IS inspected, so the engine and the marker are
      // fine and only that entry form is skipped. If this starts finding the
      // marker, ClamAV fixed it. That is NOT a licence to delete this test:
      // it forces an explicit review of Docoris's structural-safety gate
      // (owner decision D1, 2026-10-03) before that gate or the paragraph in
      // docs/CLAMD_SERVICE.md is changed. Scanner OK is a candidate-clean only.
      expect(a('control_plain_zip')).toContain('Koras.Test.Marker')
      expect(a('known_gap_zip64_streamed')).toBe('stream: OK')
    })
  })
})
