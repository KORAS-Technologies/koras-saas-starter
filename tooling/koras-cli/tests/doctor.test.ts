import { describe, it, expect } from 'vitest'
import { doctor, runChecks, CHECKS } from '../src/doctor/run.js'
import { PASS, FAIL, READY, NOT_READY } from '../src/doctor/report.js'
import {
  REPO_ROOT,
  healthyEnv,
  healthyExec,
  healthyRoutes,
  response,
  stubFetch,
  type RouteMap,
} from './helpers.js'

const EXPECTED_ROWS = [
  'Doppler',
  'GitHub',
  'Supabase',
  'ZITADEL DEV',
  'ZITADEL TEST',
  'ZITADEL STG',
  'ZITADEL PROD',
  'Vercel',
  'Fly.io',
  'Cloudflare',
  'Terraform',
  'Terraform state',
]

async function run(options: { env?: NodeJS.ProcessEnv; routes?: RouteMap; exec?: ReturnType<typeof healthyExec> } = {}) {
  return doctor({
    env: options.env ?? healthyEnv(),
    fetchImpl: stubFetch({ ...healthyRoutes(), ...(options.routes ?? {}) }),
    exec: options.exec ?? healthyExec(),
    repoRoot: REPO_ROOT,
  })
}

/** The label of every row whose mark is ✗. */
function failed(output: string): string[] {
  return output
    .split('\n')
    .filter((line) => line.endsWith(FAIL))
    .map((line) => line.replace(FAIL, '').trimEnd())
}

// ── check order and shape ────────────────────────────────────────────────────

describe('report shape', () => {
  it('declares the twelve checks in the required order', () => {
    expect(CHECKS.map((c) => c.label)).toEqual(EXPECTED_ROWS)
  })

  it('prints every row in order, with exactly one mark each', async () => {
    const { output } = await run()
    const rows = output
      .split('\n')
      .filter((line) => line.endsWith(PASS) || line.endsWith(FAIL))
    expect(rows.map((line) => line.replace(/[✓✗]/, '').trimEnd())).toEqual(EXPECTED_ROWS)
    for (const row of rows) {
      expect((row.match(/[✓✗]/g) ?? []).length).toBe(1)
    }
  })

  it('has no WARN, SKIP, counts, or timing', async () => {
    const { output } = await run({ routes: { 'api.github.com/orgs': response(404, {}) } })
    for (const forbidden of ['WARN', 'SKIP', 'skipped', 'passed:', '/12', 'ms']) {
      expect(output).not.toContain(forbidden)
    }
  })
})

// ── the happy path ───────────────────────────────────────────────────────────

describe('all checks pass', () => {
  it('reports READY FOR BOOTSTRAP and exits 0', async () => {
    const { output, code } = await run()
    expect(failed(output)).toEqual([])
    expect(output).toContain(READY)
    expect(output).not.toContain('Failures:')
    expect(code).toBe(0)
  })

  it('matches the required output exactly', async () => {
    const { output } = await run()
    expect(output).toBe(
      [
        'Koras Bootstrap Doctor',
        '',
        'Doppler          ✓',
        'GitHub           ✓',
        'Supabase         ✓',
        'ZITADEL DEV      ✓',
        'ZITADEL TEST     ✓',
        'ZITADEL STG      ✓',
        'ZITADEL PROD     ✓',
        'Vercel           ✓',
        'Fly.io           ✓',
        'Cloudflare       ✓',
        'Terraform        ✓',
        'Terraform state  ✓',
        '',
        'READY FOR BOOTSTRAP',
      ].join('\n'),
    )
  })
})

// ── individual failures ──────────────────────────────────────────────────────

describe('individual check failures', () => {
  const cases: Array<[string, string, () => Parameters<typeof run>[0]]> = [
    ['Doppler', 'rejected token', () => ({ routes: { 'api.doppler.com': response(401, {}) } })],
    ['GitHub', 'inaccessible org', () => ({ routes: { 'api.github.com/orgs': response(404, {}) } })],
    [
      'Supabase',
      'org not visible',
      () => ({ routes: { 'api.supabase.com/v1/organizations': response(200, [{ id: 'other' }]) } }),
    ],
    ['Vercel', 'team missing', () => ({ routes: { 'api.vercel.com/v2/teams': response(403, {}) } })],
    [
      'Fly.io',
      'org not visible',
      () => ({
        routes: {
          'api.fly.io/graphql': response(200, { data: { organizations: { nodes: [] } } }),
        },
      }),
    ],
    [
      'Cloudflare',
      'zone is a different domain',
      () => ({
        routes: { 'client/v4/zones': response(200, { success: true, result: { name: 'other.io' } }) },
      }),
    ],
    [
      'Terraform state',
      'organization not found',
      () => ({ routes: { 'app.terraform.io/api/v2/organizations': response(404, {}) } }),
    ],
  ]

  for (const [label, reason, options] of cases) {
    it(`fails ${label} — ${reason}`, async () => {
      const { output, code } = await run(options())
      expect(failed(output)).toEqual([label])
      expect(output).toContain(NOT_READY)
      expect(code).toBe(1)
    })
  }

  it('fails Supabase when a database password is missing', async () => {
    const env = healthyEnv()
    delete env.SUPABASE_DB_PASSWORD_STG
    const { output, code } = await run({ env })
    expect(failed(output)).toContain('Supabase')
    expect(output).toContain('SUPABASE_DB_PASSWORD_STG')
    expect(code).toBe(1)
  })

  it('fails Terraform when validate fails', async () => {
    const exec = (async (_c: string, args: string[]) =>
      args[0] === 'version'
        ? { exitCode: 0, stdout: '{"terraform_version":"1.15.8"}', stderr: '' }
        : args[0] === 'validate'
          ? { exitCode: 1, stdout: '', stderr: 'Error: Unsupported argument' }
          : { exitCode: 0, stdout: '', stderr: '' }) as ReturnType<typeof healthyExec>

    const { output, code } = await run({ exec })
    expect(failed(output)).toEqual(['Terraform'])
    expect(output).toContain('terraform validate failed')
    expect(code).toBe(1)
  })

  it('fails Terraform when the installed version is too old', async () => {
    const exec = (async () => ({
      exitCode: 0,
      stdout: '{"terraform_version":"1.2.0"}',
      stderr: '',
    })) as ReturnType<typeof healthyExec>
    const { output } = await run({ exec })
    expect(failed(output)).toEqual(['Terraform'])
    expect(output).toContain('1.2.0')
  })
})

// ── ZITADEL ──────────────────────────────────────────────────────────────────

describe('ZITADEL', () => {
  it('fails only the instance whose JSON is invalid', async () => {
    const env = healthyEnv({ ZITADEL_TEST_SERVICE_ACCOUNT_KEY_JSON: 'not json at all' })
    const { output, code } = await run({ env })
    expect(failed(output)).toEqual(['ZITADEL TEST'])
    expect(output).toContain('could not be parsed')
    expect(code).toBe(1)
  })

  it('fails when the service-account JSON is missing fields', async () => {
    const env = healthyEnv({
      ZITADEL_PROD_SERVICE_ACCOUNT_KEY_JSON: JSON.stringify({ type: 'serviceaccount' }),
    })
    const { output } = await run({ env })
    expect(failed(output)).toEqual(['ZITADEL PROD'])
    expect(output).toContain('keyId')
  })

  it('fails when authentication is rejected', async () => {
    const { output, code } = await run({
      routes: { '/oauth/v2/token': response(401, { error: 'invalid_client' }) },
    })
    // The stub is shared across instances, so all four fail together.
    expect(failed(output)).toEqual([
      'ZITADEL DEV',
      'ZITADEL TEST',
      'ZITADEL STG',
      'ZITADEL PROD',
    ])
    expect(output).toContain('Authentication failed')
    expect(code).toBe(1)
  })

  it('fails when the instance is unreachable', async () => {
    const env = healthyEnv({ ZITADEL_DEV_DOMAIN: 'unreachable.example' })
    const fetchImpl = stubFetch({
      ...healthyRoutes(),
      'unreachable.example': (() => {
        throw new Error('ENOTFOUND')
      }) as never,
    })
    const { output } = await doctor({ env, fetchImpl, exec: healthyExec(), repoRoot: REPO_ROOT })
    expect(failed(output)).toEqual(['ZITADEL DEV'])
  })

  it('accepts a domain pasted with a scheme and trailing slash', async () => {
    const env = healthyEnv({ ZITADEL_DEV_DOMAIN: 'https://auth-dev.koras.app/' })
    const { output } = await run({ env })
    expect(failed(output)).toEqual([])
  })
})

// ── failed dependencies ──────────────────────────────────────────────────────

describe('failed dependencies', () => {
  it('still reports every row when nothing is configured', async () => {
    const { output, code } = await run({ env: {} })
    const rows = output.split('\n').filter((l) => l.endsWith(PASS) || l.endsWith(FAIL))
    expect(rows).toHaveLength(12)
    // Terraform needs no credentials except the HCP token, which is absent here.
    expect(failed(output)).toEqual(EXPECTED_ROWS)
    expect(output).toContain(NOT_READY)
    expect(code).toBe(1)
  })

  it('lets Terraform pass while every credential is missing', async () => {
    const env = { TF_TOKEN_APP_TERRAFORM_IO: 'hcp.token.value.aaaaaaaa' }
    const { output } = await run({
      env,
      routes: { 'app.terraform.io/api/v2/organizations': response(401, {}) },
    })
    expect(failed(output)).not.toContain('Terraform')
    expect(failed(output)).toContain('Terraform state')
  })

  it('turns an unexpected throw into a failed row, not a crash', async () => {
    const rows = await runChecks({
      env: healthyEnv(),
      fetchImpl: stubFetch(healthyRoutes()),
      exec: healthyExec(),
      repoRoot: REPO_ROOT,
      checks: [
        {
          label: 'Exploding',
          run: async () => {
            throw new Error('boom')
          },
        },
      ],
    })
    expect(rows[0].result.passed).toBe(false)
    expect(rows[0].result.error).toContain('boom')
  })
})

// ── failure detail ───────────────────────────────────────────────────────────

describe('failure detail', () => {
  it('explains failures and says nothing about successes', async () => {
    const { output } = await run({ routes: { 'api.github.com/orgs': response(404, {}) } })
    expect(output).toContain('Failures:')
    expect(output).toContain('TF_VAR_GITHUB_ORG')
    // Nothing about the eleven that passed.
    expect(output).not.toContain('Supabase\n')
    expect(output.indexOf('Failures:')).toBeGreaterThan(output.indexOf('Terraform state'))
    expect(output.indexOf(NOT_READY)).toBeGreaterThan(output.indexOf('Failures:'))
  })
})
