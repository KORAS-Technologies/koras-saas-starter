import { describe, it, expect } from 'vitest'
import { loadProfile, isValidProfile, listProfiles } from '../src/profiles/index.js'
import { resolveSelections, validateSelections } from '../src/profiles/validator.js'

// ── isValidProfile ──────────────────────────────────────────────────────────

describe('isValidProfile', () => {
  it('accepts product', () => expect(isValidProfile('product')).toBe(true))
  it('accepts control-plane', () => expect(isValidProfile('control-plane')).toBe(true))
  it('rejects unknown profiles', () => expect(isValidProfile('saas')).toBe(false))
  it('rejects empty string', () => expect(isValidProfile('')).toBe(false))
})

// ── listProfiles ────────────────────────────────────────────────────────────

describe('listProfiles', () => {
  it('returns both profiles', () => {
    expect(listProfiles()).toEqual(expect.arrayContaining(['product', 'control-plane']))
  })
})

// ── product manifest ────────────────────────────────────────────────────────

describe('loadProfile("product")', () => {
  const { manifest, defaults } = loadProfile('product')

  it('has correct profile name', () => expect(manifest.profile).toBe('product'))
  it('has schema_version 1', () => expect(manifest.schema_version).toBe('1'))

  it('requires web app', () => expect(manifest.applications.web.required).toBe(true))
  it('makes admin optional', () => expect(manifest.applications.admin.required).toBe(false))
  it('makes marketing optional', () => expect(manifest.applications.marketing.required).toBe(false))

  it('requires api service', () => expect(manifest.services.api.required).toBe(true))
  it('makes worker optional', () => expect(manifest.services.worker.required).toBe(false))
  it('makes ai_gateway optional', () => expect(manifest.services.ai_gateway.required).toBe(false))

  it('enables tenancy', () => expect(manifest.capabilities.tenancy).toBe(true))
  it('enables control_plane_client', () => expect(manifest.capabilities.control_plane_client).toBe(true))

  it('registers as product', () => expect(manifest.registration.registers_as_product).toBe(true))
  it('has registration endpoint', () => expect(manifest.registration.endpoint).toBeDefined())

  it('has four environments', () => expect(manifest.environments).toHaveLength(4))

  it('loads defaults without error', () => expect(defaults).toBeDefined())
  it('defaults web to true', () => expect(defaults.applications?.web).toBe(true))
})

// ── control-plane manifest ──────────────────────────────────────────────────

describe('loadProfile("control-plane")', () => {
  const { manifest, defaults } = loadProfile('control-plane')

  it('has correct profile name', () => expect(manifest.profile).toBe('control-plane'))
  it('has schema_version 1', () => expect(manifest.schema_version).toBe('1'))

  it('requires platform_admin app', () => expect(manifest.applications.platform_admin.required).toBe(true))
  it('requires portal app', () => expect(manifest.applications.portal.required).toBe(true))
  it('does not include web app', () => expect(manifest.applications.web).toBeUndefined())
  it('does not include marketing app', () => expect(manifest.applications.marketing).toBeUndefined())

  it('requires api service', () => expect(manifest.services.api.required).toBe(true))
  it('requires worker service', () => expect(manifest.services.worker.required).toBe(true))
  it('requires scheduler service', () => expect(manifest.services.scheduler.required).toBe(true))
  it('does not include ai_gateway', () => expect(manifest.services.ai_gateway).toBeUndefined())

  it('does NOT register as product', () => expect(manifest.registration.registers_as_product).toBe(false))
  it('has no registration endpoint', () => expect(manifest.registration.endpoint).toBeUndefined())

  it('enables product_registry', () => expect(manifest.capabilities.product_registry).toBe(true))
  it('enables provisioning', () => expect(manifest.capabilities.provisioning).toBe(true))

  it('loads defaults without error', () => expect(defaults).toBeDefined())
})

// ── resolveSelections ───────────────────────────────────────────────────────

describe('resolveSelections — product', () => {
  const { manifest, defaults } = loadProfile('product')
  const selections = resolveSelections(manifest, defaults)

  it('web is selected (required)', () => expect(selections.applications.web).toBe(true))
  it('admin is selected (default true)', () => expect(selections.applications.admin).toBe(true))
  it('marketing is not selected (default false)', () => expect(selections.applications.marketing).toBe(false))
  it('api is selected (required)', () => expect(selections.services.api).toBe(true))
  it('ai_gateway is not selected (default false)', () => expect(selections.services.ai_gateway).toBe(false))
})

describe('resolveSelections — control-plane', () => {
  const { manifest, defaults } = loadProfile('control-plane')
  const selections = resolveSelections(manifest, defaults)

  it('platform_admin is selected', () => expect(selections.applications.platform_admin).toBe(true))
  it('portal is selected', () => expect(selections.applications.portal).toBe(true))
  it('worker is selected (required)', () => expect(selections.services.worker).toBe(true))
  it('scheduler is selected (required)', () => expect(selections.services.scheduler).toBe(true))
})

// ── validateSelections ──────────────────────────────────────────────────────

describe('validateSelections', () => {
  it('throws when a required application is disabled', () => {
    const { manifest, defaults } = loadProfile('product')
    const selections = resolveSelections(manifest, defaults)
    selections.applications.web = false
    expect(() => validateSelections(manifest, selections)).toThrow(/web.*required/)
  })

  it('throws when a required service is disabled for control-plane', () => {
    const { manifest, defaults } = loadProfile('control-plane')
    const selections = resolveSelections(manifest, defaults)
    selections.services.worker = false
    expect(() => validateSelections(manifest, selections)).toThrow(/worker.*required/)
  })

  it('does not throw for valid product selections', () => {
    const { manifest, defaults } = loadProfile('product')
    const selections = resolveSelections(manifest, defaults)
    expect(() => validateSelections(manifest, selections)).not.toThrow()
  })

  it('does not throw for valid control-plane selections', () => {
    const { manifest, defaults } = loadProfile('control-plane')
    const selections = resolveSelections(manifest, defaults)
    expect(() => validateSelections(manifest, selections)).not.toThrow()
  })
})
