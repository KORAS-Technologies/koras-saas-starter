import { describe, it, expect, beforeEach, afterAll } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * What the deploy verifies about a private service, run against a flyctl that
 * reproduces each way it can be wrong: a public address, a stopped machine, no
 * health check, a failing one.
 *
 * "Private" is a claim the Terraform and the fly.toml make. This is the step
 * that asks Fly whether it is true.
 */

const SCRIPT = templatePath('_shared', 'local', 'scripts', 'verify-private-service.sh')
const HARNESS = join(__dirname, 'private-service', 'harness.sh')

const yq = (() => {
  const r = spawnSync('yq', ['--version'], { encoding: 'utf8' })
  return r.status === 0 && /mikefarah/.test(r.stdout)
})()
const ok = (b: string) => spawnSync(b, ['--version']).status === 0
const tools = ok('bash') && ok('jq') && yq

if (process.env.CI && !tools) {
  describe('private-service tooling', () => {
    it('needs bash, jq and mikefarah yq in CI', () => expect.fail('bash, jq and yq are required in CI'))
  })
}

const PRIVATE = 'schema_version: 1\nnetwork: private\n'
const machine = (over: Record<string, unknown> = {}) => ({
  id: 'm1',
  state: 'started',
  checks: [{ name: 'clamd_tcp', status: 'passing' }],
  ...over,
})
const sixpn = { Type: 'private_v6', Address: 'fdaa:0:1::2' }

describe.skipIf(!tools)('a private service is verified after deploy', () => {
  let dir: string
  let services: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'koras-private-'))
    services = join(dir, 'services')
    mkdirSync(join(services, 'svc'), { recursive: true })
  })
  afterAll(() => rmSync(dir, { recursive: true, force: true }))

  function run(yaml: string | null, ips: unknown[], machines: unknown[]) {
    if (yaml !== null) writeFileSync(join(services, 'svc', 'service.yaml'), yaml)
    const calls = join(dir, 'calls.log')
    rmSync(calls, { force: true })
    const r = spawnSync('bash', [HARNESS, 'svc', 'p-svc-dev', services], {
      encoding: 'utf8',
      timeout: 60_000,
      env: {
        ...process.env,
        SCRIPT,
        CALLS: calls,
        FAKE_IPS: JSON.stringify(ips),
        FAKE_MACHINES: JSON.stringify(machines),
        // The wait for health is five seconds a lap; a case that is meant to
        // fail should not take five minutes to say so.
        VERIFY_PRIVATE_TIMEOUT: '1',
      },
    })
    const log = existsSync(calls) ? readFileSync(calls, 'utf8').trim().split('\n').filter(Boolean) : []
    return { status: r.status, out: r.stdout, err: r.stderr, calls: log }
  }

  it('passes: no public address, machine started, check passing', () => {
    const r = run(PRIVATE, [sixpn], [machine()])
    expect(r.status).toBe(0)
    expect(r.out).toContain('no public address')
  })

  it('passes with no addresses listed at all', () => {
    expect(run(PRIVATE, [], [machine()]).status).toBe(0)
  })

  it.each([
    ['a dedicated IPv4', { Type: 'v4', Address: '203.0.113.7' }],
    ['a shared IPv4', { Type: 'shared_v4', Address: '203.0.113.8' }],
    ['a public IPv6', { Type: 'v6', Address: '2001:db8::1' }],
    ['a type it does not recognise', { Type: 'something_new', Address: '198.51.100.1' }],
  ])('FAILS on %s -- and names the address and how to release it', (_n, ip) => {
    const r = run(PRIVATE, [sixpn, ip], [machine()])
    expect(r.status).not.toBe(0)
    expect(r.err).toContain(String(ip.Address))
    expect(r.err).toContain('flyctl ips release')
    // The address check comes first; it does not wait on machines.
    expect(r.calls.some((c) => c.startsWith('flyctl machines'))).toBe(false)
  })

  it.each([
    ['no machine exists', [], 'no machines'],
    ['a machine is stopped', [machine({ state: 'stopped' })], 'stopped'],
    ['one of two machines is not started', [machine(), machine({ id: 'm2', state: 'created' })], 'created'],
    ['a machine reports no health check', [machine({ checks: [] })], 'no health check'],
    ['a machine has no checks field at all', [{ id: 'm1', state: 'started' }], 'no health check'],
    ['a check is failing', [machine({ checks: [{ name: 'c', status: 'critical' }] })], 'failing check'],
    [
      'one of two checks is failing',
      [machine({ checks: [{ name: 'a', status: 'passing' }, { name: 'b', status: 'warning' }] })],
      'failing check',
    ],
  ])('FAILS when %s', (_n, machines, text) => {
    const r = run(PRIVATE, [sixpn], machines)
    expect(r.status).not.toBe(0)
    expect(r.err).toContain(text)
  })

  it.each([
    ['a public service', 'schema_version: 1\nnetwork: public\n'],
    ['a service with no descriptor', null],
    ['a descriptor that says nothing about the network', 'schema_version: 1\nenvironments: [dev]\n'],
  ])('does nothing for %s -- and asks Fly nothing', (_n, yaml) => {
    // A public API legitimately has a public address; applying these checks to
    // it would fail every deploy of every existing product.
    const r = run(yaml, [{ Type: 'v4', Address: '203.0.113.7' }], [])
    expect(r.status).toBe(0)
    expect(r.calls).toEqual([])
  })

  it('refuses an invalid descriptor rather than defaulting to either answer', () => {
    const r = run('schema_version: 1\nnetwork: internet\n', [sixpn], [machine()])
    expect(r.status).not.toBe(0)
    expect(r.calls).toEqual([])
  })
})
