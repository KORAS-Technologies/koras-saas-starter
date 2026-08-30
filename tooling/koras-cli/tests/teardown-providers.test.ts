import { describe, it, expect } from 'vitest'

import {
  providerDeleters,
  probeResources,
  UNIMPLEMENTED_KINDS,
} from '../src/teardown/providers/index.js'
import { inventoryFromOutputs, qualify, providerId } from '../src/teardown/inventory.js'
import { plan, RESOURCE_KINDS, type Resource } from '../src/teardown/guards.js'
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
  cloudflareApiToken: 'cf',
  terraformToken: 'tfe',
  zitadelServiceTokens: { dev: 'zt-dev', test: 'zt-test', stg: 'zt-stg', prod: 'zt-prod' },
}

const OUTPUTS = {
  githubRepository: 'KORAS-Technologies/koras-e2e-shop',
  dopplerProject: 'koras-e2e-shop',
  supabaseProjectRefs: { dev: 'ref-dev', prod: 'ref-prod' },
  zitadelProjectIds: { dev: 'z-dev' },
  zitadelOrgIds: { dev: 'org-dev' },
  zitadelDomains: { dev: 'https://zitadel-dev.example.invalid/' },
  vercelProjectIds: { 'web-dev': 'prj_a' },
  flyApps: ['koras-e2e-shop-api-dev'],
  redisDatabaseIds: { dev: 'redis-dev' },
  cloudflareRecordIds: { 'app-dev.koras-e2e-shop.example.invalid': 'rec-dev' },
  cloudflareZoneId: 'zone-1',
  terraformOrganization: 'koras',
  terraformWorkspace: 'koras-e2e-shop',
}

/** A real project's outputs. Nothing in them may ever be deleted. */
const REAL_OUTPUTS = {
  githubRepository: 'KORAS-Technologies/docoris',
  dopplerProject: 'docoris',
  supabaseProjectRefs: { dev: 'ref-dev', prod: 'ref-prod' },
  zitadelProjectIds: { dev: 'z-dev' },
  zitadelOrgIds: { dev: 'org-dev' },
  zitadelDomains: { dev: 'https://zitadel-dev.example.invalid/' },
  vercelProjectIds: { 'web-dev': 'prj_a' },
  flyApps: ['docoris-api-dev'],
  redisDatabaseIds: { dev: 'redis-dev' },
  cloudflareRecordIds: { 'app-dev.docoris.example.invalid': 'rec-dev' },
  cloudflareZoneId: 'zone-1',
  terraformOrganization: 'koras',
  terraformWorkspace: 'docoris',
}

describe('the inventory', () => {
  it('is built from what Terraform recorded, not from listing providers', () => {
    const found = inventoryFromOutputs(OUTPUTS)
    expect(found.map((r) => r.kind)).toContain('fly-app')
    expect(found.map((r) => r.kind)).toContain('github-repository')
    // One per entry in OUTPUTS. Counted rather than written down, so adding a
    // provider to the fixture cannot leave this asserting the old total.
    expect(found).toHaveLength(10)
  })

  it('orders the dependent resources before the ones holding their credentials', () => {
    const kinds = inventoryFromOutputs(OUTPUTS).map((r) => r.kind)
    expect(kinds.indexOf('fly-app')).toBeLessThan(kinds.indexOf('doppler-project'))
    expect(kinds.indexOf('supabase-project')).toBeLessThan(kinds.indexOf('github-repository'))
  })

  it('includes every provider a provision writes to', () => {
    // Twice now a whole provider has been missing from the inventory and the
    // run has reported nothing retained: Upstash in R-040, Cloudflare in R-036.
    // A missing provider has no symptom, and the count cannot show it.
    //
    // The previous version of this test listed the kinds it expected, and its
    // comment claimed to assert "the whole set". It asserted a second
    // hand-written list, which omitted Cloudflare in the same way the inventory
    // did. Compared against RESOURCE_KINDS now, so a kind that exists and is
    // never inventoried fails here.
    const kinds = new Set(inventoryFromOutputs(OUTPUTS).map((r) => r.kind))
    expect([...kinds].sort()).toEqual([...RESOURCE_KINDS].sort())
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
    expect(plan(real).retained).toHaveLength(10)
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

  it('deletes a ZITADEL project in the organization the inventory names', async () => {
    // The organization is the whole reason this deleter was hard. ZITADEL's
    // management API acts in the org of whoever holds the token, and this
    // estate has two: without the header, a project in the other one answers
    // 404, which deleteOrAlreadyGone reads as "already gone". The teardown
    // would report success and leave the project standing.
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, ALL_CREDENTIALS)['zitadel-project']
    expect(deleter, 'no ZITADEL deleter').toBeDefined()

    await deleter?.({
      kind: 'zitadel-project',
      name: 'koras-e2e-shop-zitadel-project-z-dev',
      providerId: 'z-dev',
      endpoint: 'https://zitadel-dev.example.invalid/',
      scope: 'org-dev',
      environment: 'dev',
    })

    expect(calls).toHaveLength(1)
    expect(calls[0]?.method).toBe('DELETE')
    // The instance from the inventory, not a constant, and exactly one slash
    // between base and path.
    expect(calls[0]?.url).toBe(
      'https://zitadel-dev.example.invalid/management/v1/projects/z-dev',
    )
    expect(calls[0]?.headers?.['x-zitadel-orgid']).toBe('org-dev')
    // dev's token, not another instance's. A token from the wrong instance
    // authenticates against the wrong server, does not find the project, and
    // answers 404 -- which teardown counts as success.
    expect(calls[0]?.headers?.authorization).toBe('Bearer zt-dev')
  })

  it('refuses a ZITADEL project whose organization is unknown', async () => {
    // An environment that produced a project id but no org id. Deleting anyway
    // would aim at whichever org the token belongs to; dropping it from the
    // inventory would hide it. Failing loudly is the only honest option.
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, ALL_CREDENTIALS)['zitadel-project']

    await expect(
      deleter?.({
        kind: 'zitadel-project',
        name: 'koras-e2e-shop-zitadel-project-z-dev',
        providerId: 'z-dev',
        endpoint: 'https://zitadel-dev.example.invalid',
        environment: 'dev',
      }),
    ).rejects.toThrow(/organization/)
    expect(calls, 'it called the API without knowing the org').toEqual([])
  })

  it('refuses a ZITADEL project whose instance is unknown', async () => {
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, ALL_CREDENTIALS)['zitadel-project']

    await expect(
      deleter?.({
        kind: 'zitadel-project',
        name: 'koras-e2e-shop-zitadel-project-z-dev',
        providerId: 'z-dev',
        scope: 'org-dev',
        environment: 'dev',
      }),
    ).rejects.toThrow(/instance/)
    expect(calls).toEqual([])
  })


  it('refuses a ZITADEL project in an instance it holds no token for', async () => {
    // The failure this prevents is silent, not loud: reaching for another
    // instance's token would authenticate, miss the project, and read 404 as
    // "already gone".
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, {
      ...ALL_CREDENTIALS,
      zitadelServiceTokens: { dev: 'zt-dev' },
    })['zitadel-project']

    await expect(
      deleter?.({
        kind: 'zitadel-project',
        name: 'koras-e2e-shop-zitadel-project-z-stg',
        providerId: 'z-stg',
        endpoint: 'https://zitadel-stg.example.invalid',
        scope: 'org-stg',
        environment: 'stg',
      }),
    ).rejects.toThrow(/ZITADEL_STG_SERVICE_TOKEN/)
    expect(calls, 'it fell back to another instance token').toEqual([])
  })

  it('guards a DNS record by its project, not by its hostname prefix', () => {
    // Found on a real estate: every record came back "not an acceptance-run
    // resource (no koras-e2e- prefix)". A hostname carries the project in the
    // middle -- app-dev.koras-e2e-atlas.example.com -- and the guard tests a
    // prefix, so the deleter written to stop records outliving an estate
    // retained all eight of them.
    const inventory = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')
    const record = inventory.find((r) => r.kind === 'cloudflare-record')

    expect(record?.name.startsWith('koras-e2e-shop-'), 'the guard would retain it').toBe(true)
    // And the id survives the rewrite: the record is guarded by hostname and
    // deleted by id, so clobbering providerId would send the API a hostname.
    expect(record?.providerId).toBe('rec-dev')
    expect(plan(inventory).retained).toEqual([])
  })

  it('still refuses a real project’s DNS records', () => {
    const real = qualify(inventoryFromOutputs(REAL_OUTPUTS), 'docoris')
    const record = real.find((r) => r.kind === 'cloudflare-record')
    expect(record?.name.startsWith('koras-e2e-')).toBe(false)
    expect(plan(real).deletable).toEqual([])
  })

  it('deletes a Cloudflare DNS record by id, in its zone', async () => {
    // Absent from the inventory entirely until 2026-08-27. Eight records
    // outlived an estate whose teardown reported nothing retained, because a
    // count of what the inventory holds cannot show what it omits.
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, ALL_CREDENTIALS)['cloudflare-record']
    expect(deleter, 'no Cloudflare deleter').toBeDefined()

    await deleter?.({
      kind: 'cloudflare-record',
      name: 'app-dev.koras-e2e-shop.example.invalid',
      providerId: 'rec-dev',
      scope: 'zone-1',
    })

    expect(calls).toHaveLength(1)
    expect(calls[0]?.method).toBe('DELETE')
    expect(calls[0]?.url).toBe(
      'https://api.cloudflare.com/client/v4/zones/zone-1/dns_records/rec-dev',
    )
  })

  it('deletes the HCP workspace last, by organization and name', async () => {
    // The one thing teardown could not remove, so it stayed on a by-hand list
    // holding the state of an estate that no longer existed. Addressed by name
    // because its id lived in the state being deleted.
    const { fetch, calls } = recorder()
    const deleter = providerDeleters(fetch, ALL_CREDENTIALS)['terraform-workspace']
    expect(deleter, 'no workspace deleter').toBeDefined()

    await deleter?.({
      kind: 'terraform-workspace',
      name: 'koras-e2e-shop',
      scope: 'koras',
    })

    expect(calls).toHaveLength(1)
    expect(calls[0]?.method).toBe('DELETE')
    expect(calls[0]?.url).toBe(
      'https://app.terraform.io/api/v2/organizations/koras/workspaces/koras-e2e-shop',
    )
  })

  it('deletes the workspace after everything it recorded', () => {
    const kinds = inventoryFromOutputs(OUTPUTS).map((r) => r.kind)
    expect(kinds.indexOf('terraform-workspace')).toBe(kinds.length - 1)
  })

  it('leaves no kind without a deleter', () => {
    // UNIMPLEMENTED_KINDS is empty now. It is kept because it is the only way a
    // future gap becomes visible rather than silent, and this asserts the
    // current state rather than the mechanism's removal.
    expect(UNIMPLEMENTED_KINDS).toEqual([])
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
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shop' },
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
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shop' },
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
      projectSlug: 'docoris',
      confirm: { ask: async () => 'docoris' },
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
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shop' },
    })

    expect(outcome.output).toContain('No deleter for these kinds')
    expect(outcome.output.match(/supabase-project —/g) ?? []).toHaveLength(1)
  })

  it('deletes nothing when the name typed is wrong', async () => {
    const { fetch, calls } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shopp' },
    })

    expect(calls, 'a typo in the confirmation still deleted').toEqual([])
    expect(outcome.output).toContain('Cancelled.')
  })

  it('does not accept "yes" in place of the name', async () => {
    // The whole reason it asks for the name: `yes` is a reflex by the third
    // time anyone sees it, and a name has to be read off the screen.
    const { fetch, calls } = recorder()
    await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'yes' },
    })
    expect(calls).toEqual([])
  })

  it('deletes nothing when the answer is empty', async () => {
    const { fetch, calls } = recorder()
    await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => '' },
    })
    expect(calls).toEqual([])
  })

  it('refuses without a terminal, rather than reading EOF as agreement', async () => {
    // How an automated run deletes an estate nobody meant to touch.
    const { fetch, calls } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { isTTY: false },
    })

    expect(calls).toEqual([])
    expect(outcome.output).toContain('Cancelled.')
  })

  it('never prompts when there is nothing to delete', async () => {
    // A prompt for an empty plan trains people to type the name without
    // reading it.
    let asked = false
    const { fetch } = recorder()
    await teardown({
      inventory: qualify(inventoryFromOutputs(REAL_OUTPUTS), 'docoris'),
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'docoris',
      confirm: {
        ask: async () => {
          asked = true
          return 'docoris'
        },
      },
    })
    expect(asked, 'prompted with an empty plan').toBe(false)
  })

  it('reports a failure without rolling anything back', async () => {
    const { fetch } = recorder(500)
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shop' },
    })

    expect(outcome.failed).toBe(true)
    expect(outcome.output).toContain('re-running is safe')
  })
})

describe('the confirmation prompt and the outputs cannot share stdin', () => {
  const inventory = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')

  it('an empty answer deletes nothing', async () => {
    // What a pipe actually produced. `terraform output -json` was read from
    // stdin to end-of-file, so the prompt read the same stream, got '', and
    // cancelled. Safe, and indistinguishable from the command ignoring you.
    const { fetch, calls } = recorder()
    const outcome = await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => '' },
    })

    // The cancellation notice is printed by the prompt, not returned here.
    // What matters is the only thing that is irreversible: no request went out.
    expect(calls, 'an unanswered prompt deleted something').toEqual([])
    expect(outcome.failed, 'a cancelled teardown reported failure').toBe(false)
  })

  it('deletes when the name is typed', async () => {
    const { fetch, calls } = recorder()
    await teardown({
      inventory,
      credentials: ALL_CREDENTIALS,
      fetchImpl: fetch,
      env: { KORAS_E2E_TEARDOWN: '1' },
      projectSlug: 'koras-e2e-shop',
      confirm: { ask: async () => 'koras-e2e-shop' },
    })

    expect(calls.length, 'typing the name deleted nothing').toBeGreaterThan(0)
  })
})

describe('--verify asks the providers instead of trusting the output', () => {
  const inventory = qualify(inventoryFromOutputs(OUTPUTS), 'koras-e2e-shop')
  const one = plan(inventory).deletable.filter((r) => r.kind === 'github-repository')

  /** A fetch that answers every GET with one status. */
  function answering(status: number) {
    const seen: { url: string; method: string }[] = []
    const impl = (async (url: string, init?: { method?: string }) => {
      seen.push({ url, method: init?.method ?? 'GET' })
      return { ok: status < 400, status, text: async () => '' }
    }) as never
    return { impl, seen }
  }

  it('reports 404 as gone and issues no DELETE', async () => {
    const { impl, seen } = answering(404)
    const results = await probeResources(impl, ALL_CREDENTIALS, one)

    expect(results[0]?.liveness).toBe('gone')
    // The whole point: verifying must not delete anything.
    expect(seen.every((r) => r.method === 'GET'), 'verify issued a DELETE').toBe(true)
  })

  it('reports 200 as alive — the case the delete could not have shown', async () => {
    const { impl } = answering(200)
    const results = await probeResources(impl, ALL_CREDENTIALS, one)
    expect(results[0]?.liveness).toBe('alive')
  })

  it('reports anything else as unknown rather than guessing', async () => {
    // Supabase answers 400 "Resource has been removed" for a deleted project,
    // and a 403 means the provider refused to say. Neither is `gone`, and
    // calling either one gone is inventing a result.
    for (const status of [400, 403, 500]) {
      const { impl } = answering(status)
      const results = await probeResources(impl, ALL_CREDENTIALS, one)
      expect(results[0]?.liveness, `HTTP ${status}`).toBe('unknown')
    }
  })

  it('reports a missing credential as unknown, not gone', async () => {
    // Not asking is not the same as being told the resource is absent.
    const { impl } = answering(404)
    const results = await probeResources(impl, { githubToken: undefined }, one)
    expect(results[0]?.liveness).toBe('unknown')
    expect(results[0]?.detail).toContain('credential')
  })

  it('probes the URL the deleter would have used', async () => {
    // The guarantee that makes this evidence: it runs the deleter's own code
    // path against a recording fetch and issues what that produced. A probe
    // that built its own URL could check something the delete never touched.
    const { impl, seen } = answering(404)
    await probeResources(impl, ALL_CREDENTIALS, one)

    const { fetch: deleteFetch, calls } = recorder()
    await providerDeleters(deleteFetch, ALL_CREDENTIALS)['github-repository']?.(one[0] as Resource)

    expect(seen[0]?.url).toBe(calls[0]?.url)
  })
})
