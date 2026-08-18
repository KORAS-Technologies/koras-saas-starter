import { join } from 'node:path'
import type { CommandExecutor, FetchLike, HttpResponse } from '../src/doctor/types.js'

export const REPO_ROOT = join(process.cwd(), '../..')

/** A complete, valid bootstrap environment. Individual tests break one part. */
export function healthyEnv(overrides: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    DOPPLER_TOKEN: 'dp.st.prod.aaaaaaaaaaaaaaaaaaaa',
    GITHUB_TOKEN: 'ghp_bbbbbbbbbbbbbbbbbbbbbbbb',
    SUPABASE_ACCESS_TOKEN: 'sbp_cccccccccccccccccccc',
    VERCEL_API_TOKEN: 'vercel_dddddddddddddddddddd',
    FLY_API_TOKEN: 'FlyV1_eeeeeeeeeeeeeeeeeeee',
    CLOUDFLARE_API_TOKEN: 'cf_ffffffffffffffffffff',
    TF_TOKEN_APP_TERRAFORM_IO: 'hcp.gggggggggggggggggggg',

    TF_VAR_GITHUB_ORG: 'koras-org',
    TF_VAR_PRIMARY_DOMAIN: 'koras.app',
    TF_VAR_SUPABASE_ORG_ID: 'org_supabase_1',
    TF_VAR_VERCEL_TEAM_ID: 'team_vercel_1',
    TF_VAR_FLY_ORG_SLUG: 'koras-fly',
    TF_VAR_CLOUDFLARE_ZONE_ID: 'zone_1',
  }

  for (const e of ['DEV', 'TEST', 'STG', 'PROD']) {
    env[`SUPABASE_DB_PASSWORD_${e}`] = `supabase-password-${e.toLowerCase()}`
    env[`ZITADEL_${e}_DOMAIN`] = `auth-${e.toLowerCase()}.koras.app`
    env[`ZITADEL_${e}_SERVICE_ACCOUNT_KEY_JSON`] = JSON.stringify({
      type: 'serviceaccount',
      keyId: `key-${e}`,
      key: TEST_PRIVATE_KEY,
      userId: `user-${e}`,
    })
  }

  return { ...env, ...overrides }
}

export function response(status: number, body: unknown): HttpResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  }
}

export interface RouteMap {
  [urlFragment: string]: HttpResponse | ((url: string) => HttpResponse)
}

/**
 * Matches on a URL fragment, longest first, so a specific route can override a
 * general one. An unmatched URL throws — a test must not silently pass because
 * a check called an endpoint nobody stubbed.
 */
export function stubFetch(routes: RouteMap): FetchLike & { calls: string[] } {
  const calls: string[] = []
  const keys = Object.keys(routes).sort((a, b) => b.length - a.length)

  const impl = (async (url: string) => {
    calls.push(url)
    const key = keys.find((k) => url.includes(k))
    if (!key) throw new Error(`No stub for ${url}`)
    const route = routes[key]
    return typeof route === 'function' ? route(url) : route
  }) as FetchLike & { calls: string[] }

  impl.calls = calls
  return impl
}

/** Every provider endpoint answering successfully. */
export function healthyRoutes(): RouteMap {
  return {
    'api.doppler.com': response(200, { config: { name: 'prod' } }),
    'api.github.com/orgs': response(200, { login: 'koras-org' }),
    'api.supabase.com/v1/organizations': response(200, [{ id: 'org_supabase_1', name: 'KORAS' }]),
    '.well-known/openid-configuration': (url) =>
      response(200, { issuer: `https://${new URL(url).host}` }),
    '/oauth/v2/token': response(200, { access_token: 'zitadel-access-token-value' }),
    '/auth/v1/users/me': response(200, { user: { id: 'user' } }),
    'api.vercel.com/v2/user': response(200, { user: { id: 'u' } }),
    'api.vercel.com/v2/teams': response(200, { id: 'team_vercel_1' }),
    'api.fly.io/graphql': response(200, {
      data: { organizations: { nodes: [{ slug: 'koras-fly' }] } },
    }),
    'client/v4/zones': response(200, { success: true, result: { name: 'koras.app' } }),
    'app.terraform.io/api/v2/organizations': response(200, { data: { id: 'koras' } }),
  }
}

/** Terraform present, current, and valid. */
export function healthyExec(): CommandExecutor {
  return async (_command, args) => {
    if (args[0] === 'version') {
      return { exitCode: 0, stdout: JSON.stringify({ terraform_version: '1.15.8' }), stderr: '' }
    }
    return { exitCode: 0, stdout: 'Success!', stderr: '' }
  }
}

/**
 * A throwaway RSA key, generated for tests only. It signs assertions that no
 * real ZITADEL instance would accept — the stubbed token endpoint does not
 * verify signatures, it only proves the signing path runs.
 */
export const TEST_PRIVATE_KEY = `-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCLboj2Wo2ZJjMO
7a22uPXrD2XFCYsXcUa+K1RNp6BF2YzMWQ2UlVxc2gdFhihaLAXel8B9W/+AZmAB
JBM07l5j0Hofm7ondhEVKjj85bhEx8SuGJn2FHtIgiwYh+BsrvHfIbNCJiXvPNbO
vpOpsBbBV8Iro+BTCjkR9yGG9zyPHnDRZfrca/YQLvuLVd/+jO8Y1b19RpJQGaGG
OKfkE+5YJ6+A4SBYCe+7p8KaxR/IvxqcmYmYQUdyCgL0H4mIvMQZ/YFStKe8BPWS
p2mU+Y9Y0+OiXbwnQADMSDbUdOpBD7G7SIC2GdaeMLjyCjwmgr2vYCZhrv0VhgdG
TBjy172TAgMBAAECggEABnscl1rW4DhGQSO9fdPYWvl5vrlbDITUB779IIRWU2+x
dw+OCNPt4sNEeWbiDEeBIg18+H/bkVqnsQOZUvKW5UvSpMlUU0UXbJvHvQxp4Qkg
60r73+aDYwoN6oLW5N03bHOcDoG2JK6KMBYQWpaYGVHTcU38fWHpMQo52oJa/3eo
sL8q/TD3HZsq95nrAvSDptNoDlADfYvt5VYC8qsNVCqXKmHM1MH/apM0im0orT0C
QrC78ccte6IWuZjsnGaQFT0xECfAHWXYLvZVvm5nnzfm4b8wBU/DxFCgJh/ONWeo
sB5JoS57tVybhU68+zIPFgpA5JYQraSCukGCx9bHiQKBgQC+yfW78chNSPTlzxfZ
XP7agLYV4iH3x6vx04EPladCMyIyjBbrG6rn7Fdrxks2Ep14w6mvgFHYXYjPXIFT
2Yvvd7b9Xhw7eOWyh6UBtuLYvT0v9gd49eUmU1mMwuJgemMn0ru1ngnZl098ktTj
fZ89W1um/zWNNtOevMtYkaAAWwKBgQC7FtLNqw5KaKKu1liREMcxnPBhf9MVqaFp
NyDDeaNvmbEmvy0RT3ZfZWWUSYmT1qgi5WrIhDDgznC8YTJGQrx00obQ0l2DV6Yk
qtBCYcPSmCWnw2G6simLzKfpqjuMUlJMHFHkMCqEkgPynG1GGs/TFgXAdk4WOBkm
jmrL2gY9KQKBgHA+KM+1Yv302f8JYyKBz32FE5q0Ov+m/MV8hQVCKfCMXKYYPLN8
x4NCS/wf4MejE/mkQwP5Hi2IeaBk78EAz47Gg2V0JG/opFnv62eizLpuOr0opSTI
pVNy3dAuJzhTSFp5Y+1pWKomlqDXUV+03CYgxT7uDfdSNhXBRHCK2/LZAoGAWfL2
NSXZwBKgrLinak+LxaGzvNytCww8a46ytOjFmEFnd76Ql3MB8YmZlfrpJ2gb/HMa
rP9JVLxMXXXJqxgo7W3OnZWWmjBI0/ZAHLpOYPD/obIBSbag3PLvhBtxd9yYbrlq
8e/qcUSWm010CDGZ294Js+ftUSd1iCEO3aWcPEkCgYBuRe82pk7uU30b/zEOPNSR
MgLU9Bms4qa6H1rYyoVs94i79mxKzAw8r6oSHOCHezuBIF4D7hKYrpH9V0QsxAYe
9gpENJx/zOhOq7SAgb/cqPG7LqJUBqQfQsw29f+81TWKR8s3FWxgdySrpfK0WH6P
mPj14C9J1NXtb15qLT617g==
-----END PRIVATE KEY-----`
