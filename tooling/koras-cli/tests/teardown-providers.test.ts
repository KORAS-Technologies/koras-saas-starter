import { describe, it, expect } from 'vitest'

import { providerDeleters, UNIMPLEMENTED_KINDS } from '../src/teardown/providers/index.js'
import { inventoryFromOutputs, qualify, providerId } from '../src/teardown/inventory.js'
import { plan, type Resource } from '../src/teardown/guards.js'
import { teardown } from '../src/teardown/run.js'
import type { FetchLike } from '../src/doctor/types.js'

/**
 * The delete calls, exercised against a double.
 *
 * Nothing in this file reaches a provider, and nothing in the repository does:
 * `fetchImpl` is injected everywhere and no test supplies a real one. That is
 * worth stating plainly for this suite in particular — a green run here means
 * the requests are shaped correctly and says nothing about whether a provider
 * accepts them.
 */

function recorder(status = 204): {
  fetch: FetchLike
  calls: Array<{ url: string; method?: string; headers?: Record<string, string> }>
} {
  const calls: Array<{ url: string; method?: string; headers?: Record<string, string> }> = []
  const fetch: FetchLike = (url, init) => {
    calls.push({ url, method: init?.method, headers: init?.headers })
    return Promise.resolve({ ok: status < 400, status, text: () => Promise.resolve('') })
  }
  return { fetch, calls }
}

const ALL_CREDENTIALS = {
  githubToken: 'gh',
  dopplerToken: 'dp',
  supabaseToken: 'sb',
  upstashEmail: 'ops@example.invalid',
  upstashApiKey: 'up',
  vercelToken: 'vc',
  flyToken: 'fly',
}

const OUTPUTS = {
  githubRepository: 'KORAS-Technologies/koras-e2e-shop',
  dopplerProject: 'koras-e2e-shop',
  supabaseProjectRefs: { dev: 'ref-dev', prod: 'ref-prod' },
  zitadelProjectIds: { dev: 'z-dev' },
  vercelProjectIds: { 'web-dev': 'prj_a' },
  flyApps: ['koras-e2e-shop-api-dev'],
  redisDatabaseIds: { dev: 'redis-dev' },
}

/** A real project's outputs. Nothing in them may ever be deleted. */
const REAL_OUTPUTS = {
  githubRepository: 'KORAS-Technologies/docoris',
  dopplerProject: 'docoris',
  supabaseProjectRefs: { dev: 'ref-dev', prod: 'ref-prod' },
  zitadelProjectIds: { dev: 'z-dev' },
  vercelProjectIds: { 'web-dev': 'prj_a' },
  flyApps: ['docoris-api-dev'],
  redisDatabaseIds: { dev: 'redis-dev' },
}

describe('the inventory', () => {
  it('is built from what Terraform recorded, not from listing providers', () => {
    const found = inventoryFromOutputs(OUTPUTS)
    expect(found.map((r) => r.kind)).toContain('fly-app')
    expect(found.map((r) => r.kind)).toContain('github-repository')
    expect(found).toHaveLength(8)
  })

  it('orders the dependent resources before the ones holding their credentials', () => {
    const kinds = inventoryFromOutputs(OUTPUTS).map((r) => r.kind)
    expect(kinds.indexOf('fly-app')).toBeLessThan(kinds.indexOf('doppler-project'))
    expect(kinds.indexOf('supabase-project')).toBeLessThan(kinds.indexOf('github-repository'))
  })

  it('includes ZITADEL even though nothing deletes it', () => {
    // Omitting it would report a complete teardown while leaving projects behind.
    expect(inventoryFromOutputs(OUTPUTS).map((r) => r.kind)).toContain('zitadel-project')
  })

  it('gives an opaque id a name the guards can judge', () => {
    // A Supabase ref contains no project name, so the prefix guard would refuse
    // every one of them. What makes it safe to delete is the project it belongs
    // to, so that is what the guard is shown.
    const qualified = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')
    const supabase = qualified.find((r) => r.kind === 'supabase-project')!

    expect(supabase.name.startsWith('koras-e2e-shop')).toBe(true)
    expect(providerId(supabase), 'the provider must still get the bare ref').toBe('ref-dev')
  })

  it('leaves a repository name alone, because owner/repo is what the API wants', () => {
    const qualified = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')
    const repo = qualified.find((r) => r.kind === 'github-repository')!
    expect(providerId(repo)).toBe('KORAS-Technologies/koras-e2e-shop')
  })

  it('still refuses a project that is not an acceptance run', () => {
    // Qualifying must not become a way to smuggle an id past the guard.
    //
    // A real project's outputs, not the acceptance ones relabelled: the first
    // version of this test passed `docoris` as the slug alongside outputs that
    // named koras-e2e-shop, and the three correctly-named resources in them
    // were rightly still deletable. Incoherent input, and it proved nothing.
    const real = qualify(inventoryFromOutputs(REAL_OUTPUTS), 'docoris')
    expect(plan(real).deletable).toEqual([])
    expect(plan(real).retained).toHaveLength(8)
  })
})

describe('the delete calls', () => {
  const resource = (kind: Resource['kind'], name: string, id?: string): Resource => ({
    kind,
    name,
    providerId: id,
  })

  it('sends DELETE, and to the documented endpoint', async () => {
    const { fetch, calls } = recorder()
    const deleters = providerDeleters(fetch, ALL_CREDENTIALS)

    await deleters['github-repository']!(
      resource('github-repository', 'KORAS-Technologies/koras-e2e-shop'),
    )
    expect(calls[0].method).toBe('DELETE')
    expect(calls[0].url).toBe('https://api.github.com/repos/KORAS-Technologies/koras-e2e-shop')
  })

  it('authenticates every provider', async () => {
    const { fetch, calls } = recorder()
    const deleters = providerDeleters(fetch, ALL_CREDENTIALS)

    await deleters['doppler-project']!(resource('doppler-project', 'koras-e2e-shop'))
    await deleters['supabase-project']!(resource('supabase-project', 'x', 'ref-dev'))
    await deleters['fly-app']!(resource('fly-app', 'koras-e2e-shop-api-dev'))
    await deleters['vercel-project']!(resource('vercel-project', 'x', 'prj_a'))
    await deleters['upstash-database']!(resource('upstash-database', 'x', 'redis-dev'))

    for (const call of calls) {
      expect(call.headers?.authorization, `${call.url} sent no credential`).toBeTruthy()
    }
  })

  it('uses basic auth for Upstash, which does not take a bearer token', async () => {
    const { fetch, calls } = recorder()
    const deleters = providerDeleters(fetch, ALL_CREDENTIALS)
    await deleters['upstash-database']!(resource('upstash-database', 'x', 'redis-dev'))
    expect(calls[0].headers?.authorization?.startsWith('Basic ')).toBe(true)
  })

  it('treats an already-deleted resource as success', async () => {
    // Teardown's job is that the thing is gone. Failing on a 404 would make a
    // re-run after a partial teardown impossible.
    const { fetch } = recorder(404)
    const deleters = providerDeleters(fetch, ALL_CREDENTIALS)
    await expect(
      deleters['doppler-project']!(resource('doppler-project', 'koras-e2e-shop')),
    ).resolves.toBeUndefined()
  })

  it('does not swallow a real failure', async () => {
    const { fetch } = recorder(500)
    const deleters = providerDeleters(fetch, ALL_CREDENTIALS)
    await expect(
      deleters['doppler-project']!(resource('doppler-project', 'koras-e2e-shop')),
    ).rejects.toThrow()
  })

  it('offers no deleter for a credential that is not set', async () => {
    const { fetch } = recorder()
    const deleters = providerDeleters(fetch, { githubToken: 'gh' })
    expect(deleters['github-repository']).toBeDefined()
    expect(deleters['supabase-project']).toBeUndefined()
  })

  it('offers none for ZITADEL, and says why', () => {
    const { fetch } = recorder()
    expect(providerDeleters(fetch, ALL_CREDENTIALS)['zitadel-project']).toBeUndefined()
    expect(UNIMPLEMENTED_KINDS.find((u) => u.kind === 'zitadel-project')?.reason).toMatch(/JWT/)
  })
})

describe('the teardown command', () => {
  const inventory = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')

  it('deletes nothing by default, and says so', async () => {
    const { fetch, calls } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: {},
    })

    expect(calls, 'a dry run issued a request').toEqual([])
    expect(outcome.output).toContain('DRY RUN')
    expect(outcome.failed).toBe(false)
  })

  it('deletes when explicitly enabled', async () => {
    const { fetch, calls } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
    })

    expect(calls.length).toBeGreaterThan(0)
    expect(calls.every((c) => c.method === 'DELETE')).toBe(true)
    expect(outcome.failed).toBe(false)
  })

  it('never touches a resource the guards refuse', async () => {
    const { fetch, calls } = recorder()
    await teardown({
      inventory: qualify(inventoryFromOutputs(REAL_OUTPUTS), 'docoris'),
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
    })
    expect(calls, 'a non-acceptance project was contacted').toEqual([])
  })

  it('names a missing credential once, not once per resource', async () => {
    const { fetch } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: { githubToken: 'gh' },
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
    })

    expect(outcome.output).toContain('No deleter for these kinds')
    expect(outcome.output.match(/supabase-project —/g) ?? []).toHaveLength(1)
  })

  it('reports a failure without rolling anything back', async () => {
    const { fetch } = recorder(500)
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
    })

    expect(outcome.failed).toBe(true)
    expect(outcome.output).toContain('re-running is safe')
  })
})
