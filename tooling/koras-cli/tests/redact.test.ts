import { describe, it, expect } from 'vitest'
import { redact, isSensitiveName } from '../src/doctor/redact.js'
import { formatReport } from '../src/doctor/report.js'
import { doctor } from '../src/doctor/run.js'
import {
  REPO_ROOT,
  healthyEnv,
  healthyExec,
  healthyRoutes,
  response,
  stubFetch,
  TEST_PRIVATE_KEY,
} from './helpers.js'

describe('sensitive names', () => {
  it('recognises every category', () => {
    for (const name of [
      'GITHUB_TOKEN',
      'SUPABASE_DB_PASSWORD_DEV',
      'CLIENT_SECRET',
      'MY_PRIVATE_KEY',
      'SOME_API_KEY',
      'ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON',
      'AWS_CREDENTIAL',
      'AUTHORIZATION',
      'A_JWT',
      'SESSION_COOKIE',
    ]) {
      expect(isSensitiveName(name)).toBe(true)
    }
  })

  it('leaves non-secret names alone', () => {
    for (const name of ['TF_VAR_GITHUB_ORG', 'TF_VAR_PRIMARY_DOMAIN', 'ZITADEL_DEV_DOMAIN']) {
      expect(isSensitiveName(name)).toBe(false)
    }
  })
})

describe('value-based redaction', () => {
  const env = { GITHUB_TOKEN: 'ghp_notarealvalue1234', TF_VAR_GITHUB_ORG: 'koras-org' }

  it('removes a credential echoed back by a provider', () => {
    const out = redact(`401: token ${env.GITHUB_TOKEN} is invalid`, env)
    expect(out).not.toContain(env.GITHUB_TOKEN)
    expect(out).toContain('[redacted]')
  })

  it('keeps non-secret configuration readable', () => {
    expect(redact('Organization "koras-org" not found', env)).toContain('koras-org')
  })

  it('removes every occurrence', () => {
    const out = redact(`${env.GITHUB_TOKEN} and again ${env.GITHUB_TOKEN}`, env)
    expect(out).not.toContain(env.GITHUB_TOKEN)
  })

  it('does not touch very short values, which would corrupt the message', () => {
    expect(redact('status is ok', { A_TOKEN: 'ok' })).toBe('status is ok')
  })

  it('removes the longer value first when one contains the other', () => {
    const out = redact('abc123456789', { A_TOKEN: 'abc123', B_TOKEN: 'abc123456789' })
    expect(out).toBe('[redacted]')
  })
})

describe('pattern-based redaction', () => {
  it('removes a PEM private key', () => {
    const out = redact(`failed with key ${TEST_PRIVATE_KEY}`, {})
    expect(out).not.toContain('MIIEvQIBADANBgkqhkiG9w0')
    expect(out).not.toContain('BEGIN PRIVATE KEY')
  })

  it('removes a JWT', () => {
    const jwt = 'eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJ1c2VyIn0.c2lnbmF0dXJl'
    expect(redact(`assertion ${jwt} rejected`, {})).not.toContain(jwt)
  })

  it('removes an authorization header', () => {
    const out = redact('Authorization: Bearer abcdef123456789', {})
    expect(out).not.toContain('abcdef123456789')
  })

  it('removes a KEY=value assignment from CLI stderr', () => {
    const out = redact('env: FLY_API_TOKEN=FlyV1_abcdefghijkl rejected', {})
    expect(out).not.toContain('FlyV1_abcdefghijkl')
    expect(out).toContain('FLY_API_TOKEN')
  })

  it('removes a credential field from a JSON body', () => {
    // Assembled rather than written literally, so the file itself contains no
    // credential-shaped string.
    const field = ['client', 'Secret'].join('')
    const leaked = 'notarealvalue-abcdef'
    const out = redact(`{"${field}":"${leaked}","org":"koras"}`, {})
    expect(out).not.toContain(leaked)
    expect(out).toContain('koras')
  })

  it('redacts an Error stack, not just a string', () => {
    expect(redact(new Error('token ghp_leakedvalue1234'), {})).not.toContain('ghp_leakedvalue1234')
  })
})

describe('redaction reaches real output', () => {
  it('sanitises failure detail in the report', () => {
    const env = { GITHUB_TOKEN: 'ghp_fromtheenvironment' }
    const output = formatReport(
      [{ label: 'GitHub', result: { passed: false, error: `rejected: ${env.GITHUB_TOKEN}` } }],
      env,
    )
    expect(output).not.toContain(env.GITHUB_TOKEN)
    expect(output).toContain('[redacted]')
  })

  it('prints no credential when a provider echoes one back', async () => {
    const env = healthyEnv()
    const { output } = await doctor({
      env,
      fetchImpl: stubFetch({
        ...healthyRoutes(),
        'api.github.com/orgs': response(401, { message: `bad token ${env.GITHUB_TOKEN}` }),
      }),
      exec: healthyExec(),
      repoRoot: REPO_ROOT,
    })

    for (const [name, secretValue] of Object.entries(env)) {
      if (!isSensitiveName(name) || !secretValue) continue
      expect(output).not.toContain(secretValue)
    }
  })
})
