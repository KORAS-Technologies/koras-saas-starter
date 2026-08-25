import { describe, it, expect } from 'vitest'
import {
  E2E_PREFIX,
  PROTECTED_NAMES,
  isDeletable,
  plan,
  apply,
  teardownEnabled,
  formatPlan,
  type Resource,
} from '../src/teardown/guards.js'

/**
 * The guards on the one helper whose job is destruction.
 *
 * These matter more than the acceptance tests they support. Teardown deletes
 * GitHub repositories, Doppler projects, and Supabase projects, and every one
 * of those deletions is unrecoverable — so the interesting assertions here are
 * all about what it refuses, and the deleters are injected so that a test for
 * "would it delete the Control Plane" can be written without any possibility
 * of finding out the hard way.
 */

const ENABLED = { KORAS_E2E_TEARDOWN: '1' }

function resource(kind: Resource['kind'], name: string): Resource {
  return { kind, name }
}

describe('what teardown will delete', () => {
  it('accepts a correctly prefixed acceptance-run resource', () => {
    expect(isDeletable(`${E2E_PREFIX}shop`).ok).toBe(true)
  })

  it('refuses anything without the acceptance-run prefix', () => {
    for (const name of ['docoris', 'shop', 'my-project', 'e2e-shop', 'koras-e2e']) {
      expect(isDeletable(name).ok, name).toBe(false)
    }
  })

  it('refuses the bare prefix, which names no single resource', () => {
    expect(isDeletable(E2E_PREFIX).ok).toBe(false)
  })

  it('refuses every protected estate resource', () => {
    for (const name of PROTECTED_NAMES) {
      expect(isDeletable(name).ok, name).toBe(false)
    }
  })

  it('refuses wildcards and traversal, which reach past what was named', () => {
    for (const name of [`${E2E_PREFIX}*`, `${E2E_PREFIX}../docoris`, `${E2E_PREFIX}sh?p`]) {
      expect(isDeletable(name).ok, name).toBe(false)
    }
  })

  it('refuses an empty name', () => {
    expect(isDeletable('').ok).toBe(false)
    expect(isDeletable('   ').ok).toBe(false)
  })
})

describe('planning a teardown', () => {
  const inventory: Resource[] = [
    resource('github-repository', `KORAS-Technologies/${E2E_PREFIX}shop`),
    resource('doppler-project', `${E2E_PREFIX}shop`),
    resource('supabase-project', `${E2E_PREFIX}shop-dev`),
    resource('github-repository', 'KORAS-Technologies/koras-control-plane'),
    resource('doppler-project', 'docoris'),
  ]

  it('separates acceptance-run resources from everything else', () => {
    const result = plan(inventory)
    expect(result.deletable.map((r) => r.name)).toEqual([
      `KORAS-Technologies/${E2E_PREFIX}shop`,
      `${E2E_PREFIX}shop`,
      `${E2E_PREFIX}shop-dev`,
    ])
    expect(result.retained.map((r) => r.resource.name)).toEqual([
      'KORAS-Technologies/koras-control-plane',
      'docoris',
    ])
  })

  it('applies the prefix rule to a repository name, not its owner', () => {
    // `KORAS-Technologies/koras-e2e-shop` is deletable and
    // `koras-e2e-org/docoris` is not, though both contain the prefix.
    expect(plan([resource('github-repository', `koras-e2e-org/docoris`)]).deletable).toEqual([])
  })

  it('gives a reason for everything it retains', () => {
    for (const { reason } of plan(inventory).retained) {
      expect(reason).not.toBe('')
    }
  })
})

describe('applying a teardown', () => {
  const deletable = plan([
    resource('github-repository', `KORAS-Technologies/${E2E_PREFIX}shop`),
    resource('doppler-project', `${E2E_PREFIX}shop`),
  ])

  it('deletes nothing unless it was explicitly enabled', async () => {
    const seen: string[] = []
    const results = await apply(deletable, {
      env: {},
      deleters: {
        'github-repository': async (r) => void seen.push(r.name),
        'doppler-project': async (r) => void seen.push(r.name),
      },
    })

    expect(seen).toEqual([])
    expect(results.every((r) => r.status === 'skipped')).toBe(true)
  })

  it('is disabled by default', () => {
    expect(teardownEnabled({})).toBe(false)
    expect(teardownEnabled({ KORAS_E2E_TEARDOWN: 'true' })).toBe(false)
    expect(teardownEnabled(ENABLED)).toBe(true)
  })

  it('deletes the acceptance-run resources when enabled', async () => {
    const seen: string[] = []
    const results = await apply(deletable, {
      env: ENABLED,
      deleters: {
        'github-repository': async (r) => void seen.push(r.name),
        'doppler-project': async (r) => void seen.push(r.name),
      },
    })

    expect(seen).toEqual([`KORAS-Technologies/${E2E_PREFIX}shop`, `${E2E_PREFIX}shop`])
    expect(results.every((r) => r.status === 'deleted')).toBe(true)
  })

  it('re-checks each name at the moment it deletes it', async () => {
    // A plan can be filtered, mapped, or concatenated between being made and
    // being applied. The guard has to hold for the argument actually passed.
    const forged = { deletable: [resource('doppler-project', 'docoris')], retained: [] }
    const seen: string[] = []
    const results = await apply(forged, {
      env: ENABLED,
      deleters: { 'doppler-project': async (r) => void seen.push(r.name) },
    })

    expect(seen).toEqual([])
    expect(results[0].status).toBe('skipped')
  })

  it('keeps going when one provider fails, and reports each outcome', async () => {
    const results = await apply(deletable, {
      env: ENABLED,
      deleters: {
        'github-repository': async () => {
          throw new Error('404 not found')
        },
        'doppler-project': async () => {},
      },
    })

    expect(results.map((r) => r.status)).toEqual(['failed', 'deleted'])
    expect(results[0].detail).toContain('404')
  })

  it('skips a kind it has no deleter for rather than assuming success', async () => {
    const results = await apply(deletable, { env: ENABLED, deleters: {} })
    expect(results.every((r) => r.status === 'skipped')).toBe(true)
  })
})

describe('reporting a teardown', () => {
  it('names every resource and every reason', () => {
    const result = plan([
      resource('doppler-project', `${E2E_PREFIX}shop`),
      resource('doppler-project', 'koras-control-plane'),
    ])
    const text = formatPlan(result)

    expect(text).toContain(`${E2E_PREFIX}shop`)
    expect(text).toContain('koras-control-plane')
    // The prefix rule answers first, so that is the reason reported. The
    // protected list never gets a say here -- no protected name carries the
    // prefix -- which is why it is asserted directly rather than through plan().
    expect(text).toContain('not an acceptance-run resource')
  })
})
