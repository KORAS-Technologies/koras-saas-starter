import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  NO_ENTITLEMENTS,
  NO_TENANT_FEATURES,
  canOpenModule,
  isEntitled,
  isFeatureEnabled,
  moduleForPath,
  parseTenantFeatures,
  productConfig,
  resolveNavigation,
} from './index.js'
import type { AccessContext, NavigationConfig, ProductModule } from './index.js'

/**
 * What the signed-in sidebar shows, and — the half that matters — what it
 * refuses.
 *
 * `resolveNavigation` is the only thing deciding which modules a caller sees,
 * and `canOpenModule` is the same decision the middleware makes about the URL.
 * If those two ever disagree, hidden navigation has quietly become the
 * authorization boundary, which is the failure this whole design exists to
 * prevent. These tests are that argument, executable.
 *
 * They live in the generated product rather than in the starter because the
 * code does.
 */

/* -------------------------------------------------------------------------- */
/* Fixtures                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Access objects are written as literals rather than derived from the
 * permissions package.
 *
 * `as const` narrows each array to its own literal types, which is what makes
 * it assignable to the permission union without this file importing anything
 * that would have to be interpolated at generation time. The permissions
 * package has its own tests for the derivation; this file is about what the
 * resolver does with the result.
 */
const ADMIN = {
  granted: true,
  role: 'product_admin',
  permissions: ['product.access', 'settings.manage', 'settings.read', 'team.manage', 'team.read'],
} as const

const MEMBER = {
  granted: true,
  role: 'product_member',
  permissions: ['product.access'],
} as const

const DENIED = { granted: false, role: null, permissions: [] } as const

function context(overrides: Partial<AccessContext> = {}): AccessContext {
  return {
    access: ADMIN,
    capabilities: ['billing', 'branding', 'tenancy'],
    entitlements: NO_ENTITLEMENTS,
    features: NO_TENANT_FEATURES,
    organizationRoles: ['organization_admin'],
    ...overrides,
  }
}

function module(overrides: Partial<ProductModule> = {}): ProductModule {
  return {
    id: 'reports',
    label: 'Reports',
    icon: 'chart',
    href: '/dashboard/reports',
    group: 'work',
    order: 10,
    ...overrides,
  }
}

function config(modules: ProductModule[]): NavigationConfig {
  return {
    groups: [
      { id: 'primary', label: '', order: 0 },
      { id: 'work', label: 'Work', order: 10 },
      { id: 'administration', label: 'Administration', order: 900 },
    ],
    modules,
  }
}

function ids(groups: ReturnType<typeof resolveNavigation>): string[] {
  return groups.flatMap((group) => group.items.map((item) => item.id))
}

/* -------------------------------------------------------------------------- */
/* Product access                                                             */
/* -------------------------------------------------------------------------- */

test('a caller without product access sees nothing at all', () => {
  const resolved = resolveNavigation(config([module(), module({ id: 'home', group: 'primary' })]), {
    ...context(),
    access: DENIED,
  })
  assert.deepEqual(resolved, [])
})

test('a module with no requirements is visible to any caller with access', () => {
  assert.deepEqual(ids(resolveNavigation(config([module()]), context({ access: MEMBER }))), [
    'reports',
  ])
})

/* -------------------------------------------------------------------------- */
/* Permissions                                                                */
/* -------------------------------------------------------------------------- */

test('a permission the caller lacks hides the module', () => {
  const nav = config([module({ requiredPermissions: ['team.manage'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: MEMBER }))), [])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: ADMIN }))), ['reports'])
})

test('every named permission must be held, not just one of them', () => {
  const nav = config([module({ requiredPermissions: ['product.access', 'team.manage'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: MEMBER }))), [])
})

test('a permission failure hides rather than locks, whatever the module asked for', () => {
  // A locked entry advertises that an area exists. For a plan that is the
  // point; for an authorization refusal it leaks the shape of the admin
  // surface to somebody who may not have it.
  const nav = config([
    module({ requiredPermissions: ['team.manage'], lockedBehavior: 'lock' }),
  ])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: MEMBER }))), [])
})

/* -------------------------------------------------------------------------- */
/* Role gates                                                                 */
/* -------------------------------------------------------------------------- */

test('productAdminOnly admits a product administrator and refuses a member', () => {
  const nav = config([module({ productAdminOnly: true })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: ADMIN }))), ['reports'])
  assert.deepEqual(ids(resolveNavigation(nav, context({ access: MEMBER }))), [])
})

test('ownerOnly reads the organization role, not the product role', () => {
  // An administrator is a product_admin and is still not the owner. Collapsing
  // the two would make every administrator an owner, silently.
  const nav = config([module({ ownerOnly: true })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), [])
  assert.deepEqual(
    ids(resolveNavigation(nav, context({ organizationRoles: ['organization_owner'] }))),
    ['reports'],
  )
})

/* -------------------------------------------------------------------------- */
/* Capabilities                                                               */
/* -------------------------------------------------------------------------- */

test('a capability this product was not generated with hides the module', () => {
  const nav = config([module({ requiredCapabilities: ['ai_gateway'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), [])
})

test('a capability the product has admits the module', () => {
  const nav = config([module({ requiredCapabilities: ['billing', 'tenancy'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), ['reports'])
})

test('a missing capability hides even when the module asked to be locked', () => {
  // There is no code to link to. Offering an upgrade for something this
  // repository does not contain is an offer nobody can fulfil.
  const nav = config([module({ requiredCapabilities: ['ai_gateway'], lockedBehavior: 'lock' })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), [])
})

/* -------------------------------------------------------------------------- */
/* Entitlements                                                               */
/* -------------------------------------------------------------------------- */

const ENTITLED = {
  resolved: true,
  plan: 'growth',
  features: { advanced_reporting: { enabled: true, limit: null } },
}

const NOT_ENTITLED = {
  resolved: true,
  plan: 'free',
  features: { advanced_reporting: { enabled: false, limit: null } },
}

test('an entitlement the plan includes admits the module', () => {
  const nav = config([module({ requiredEntitlements: ['advanced_reporting'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ entitlements: ENTITLED }))), ['reports'])
})

test('an entitlement the plan lacks hides the module by default', () => {
  const nav = config([module({ requiredEntitlements: ['advanced_reporting'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ entitlements: NOT_ENTITLED }))), [])
})

test('a module asking to be locked is shown, disabled, with a reason', () => {
  const nav = config([
    module({ requiredEntitlements: ['advanced_reporting'], lockedBehavior: 'lock' }),
  ])
  const [group] = resolveNavigation(nav, context({ entitlements: NOT_ENTITLED }))
  assert.equal(group?.items[0]?.state, 'locked')
  assert.equal(group?.items[0]?.lockedReason, 'Not included in your plan')
})

test('an unresolved entitlement set counts as not entitled', () => {
  // The opposite convention would make an unreachable Control Plane the way to
  // obtain a paid feature, and would do it silently.
  const nav = config([module({ requiredEntitlements: ['advanced_reporting'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context({ entitlements: NO_ENTITLEMENTS }))), [])
  assert.equal(isEntitled(NO_ENTITLEMENTS, 'advanced_reporting'), false)
})

test('an unresolved plan changes nothing about ungated modules', () => {
  // The product keeps working when the platform is unreachable. Only the
  // plan-gated part of the sidebar goes quiet.
  const nav = config([module(), module({ id: 'paid', requiredEntitlements: ['x'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), ['reports'])
})

/* -------------------------------------------------------------------------- */
/* Tenant features                                                            */
/* -------------------------------------------------------------------------- */

test('a feature the tenant has not enabled hides the module', () => {
  const nav = config([module({ requiredFeatures: ['beta_search'] })])
  assert.deepEqual(ids(resolveNavigation(nav, context())), [])
  assert.deepEqual(
    ids(resolveNavigation(nav, context({ features: { beta_search: true } }))),
    ['reports'],
  )
})

test('a feature switched off explicitly is off', () => {
  assert.equal(isFeatureEnabled({ beta_search: false }, 'beta_search'), false)
  assert.equal(isFeatureEnabled(NO_TENANT_FEATURES, 'beta_search'), false)
})

test('a disabled feature can lock rather than hide', () => {
  const nav = config([module({ requiredFeatures: ['beta_search'], lockedBehavior: 'lock' })])
  const [group] = resolveNavigation(nav, context())
  assert.equal(group?.items[0]?.lockedReason, 'Not enabled for your organisation')
})

/* -------------------------------------------------------------------------- */
/* Grouping and ordering                                                      */
/* -------------------------------------------------------------------------- */

test('groups come back in group order and modules in module order', () => {
  const nav = config([
    module({ id: 'b', order: 20 }),
    module({ id: 'a', order: 10 }),
    module({ id: 'home', group: 'primary', order: 0 }),
    module({ id: 'settings', group: 'administration', order: 0 }),
  ])
  assert.deepEqual(ids(resolveNavigation(nav, context())), ['home', 'a', 'b', 'settings'])
})

test('a group with nothing left in it is not rendered', () => {
  // An empty heading reads as a section that failed to load.
  const nav = config([module({ group: 'work', requiredPermissions: ['team.manage'] })])
  assert.deepEqual(resolveNavigation(nav, context({ access: MEMBER })), [])
})

test('a module in a group nobody declared is dropped rather than crashing', () => {
  const nav = config([module({ group: 'nowhere' })])
  assert.deepEqual(resolveNavigation(nav, context()), [])
})

/* -------------------------------------------------------------------------- */
/* The route gate                                                             */
/* -------------------------------------------------------------------------- */

test('the longest matching module owns a path', () => {
  const nav = config([
    module({ id: 'settings', href: '/dashboard/settings' }),
    module({ id: 'team', href: '/dashboard/settings/team' }),
  ])
  assert.equal(moduleForPath(nav, '/dashboard/settings/team')?.id, 'team')
  assert.equal(moduleForPath(nav, '/dashboard/settings/team/invite')?.id, 'team')
  assert.equal(moduleForPath(nav, '/dashboard/settings')?.id, 'settings')
})

test('a prefix that is not a whole path segment does not match', () => {
  // /dashboard/settings-export must not inherit the settings module's gate --
  // in either direction. Admitting it would apply the wrong rule; refusing it
  // would refuse a route nobody registered.
  const nav = config([module({ id: 'settings', href: '/dashboard/settings' })])
  assert.equal(moduleForPath(nav, '/dashboard/settings-export'), undefined)
})

test('a path no module claims is nobody’s, and the caller is not refused for it', () => {
  assert.equal(moduleForPath(config([module()]), '/dashboard/anything'), undefined)
})

test('the route gate and the sidebar agree, module for module', () => {
  // The property the whole design rests on: anything hidden for an
  // authorization reason is also refused at the URL, and anything shown is
  // admitted. Checked across every caller shape rather than asserted once.
  const nav = config([
    module({ id: 'open' }),
    module({ id: 'permissioned', requiredPermissions: ['team.manage'] }),
    module({ id: 'adminOnly', productAdminOnly: true }),
    module({ id: 'ownerOnly', ownerOnly: true }),
    module({ id: 'capability', requiredCapabilities: ['ai_gateway'] }),
  ])

  for (const access of [ADMIN, MEMBER, DENIED]) {
    for (const roles of [['organization_admin'], ['organization_owner'], ['member']]) {
      const ctx = context({ access, organizationRoles: roles })
      const shown = new Set(ids(resolveNavigation(nav, ctx)))
      for (const candidate of nav.modules) {
        assert.equal(
          shown.has(candidate.id),
          canOpenModule(candidate, ctx),
          candidate.id + ' for ' + access.role + ' as ' + roles.join(),
        )
      }
    }
  }
})

/* -------------------------------------------------------------------------- */
/* The shipped registry                                                       */
/* -------------------------------------------------------------------------- */

test('every default module belongs to a declared group', () => {
  const declared = new Set(productConfig.navigation.groups.map((group) => group.id))
  for (const entry of productConfig.navigation.modules) {
    assert.ok(declared.has(entry.group), entry.id + ' is in group ' + entry.group)
  }
})

test('a plain member sees the product but not its administration', () => {
  const resolved = resolveNavigation(
    productConfig.navigation,
    context({ access: MEMBER, capabilities: productConfig.product.capabilities }),
  )
  assert.deepEqual(ids(resolved), ['home'])
})

test('an administrator sees the administration group', () => {
  const resolved = resolveNavigation(
    productConfig.navigation,
    context({ access: ADMIN, capabilities: productConfig.product.capabilities }),
  )
  assert.deepEqual(ids(resolved), ['home', 'team', 'settings'])
})

/* -------------------------------------------------------------------------- */
/* The feature parser                                                         */
/* -------------------------------------------------------------------------- */

test('a feature switch must be a boolean, not something boolean-ish', () => {
  // `tenant_settings.features` is customer-writable jsonb. Coercing would make
  // every one of these enable the feature, and "no" enabling the beta is the
  // kind of bug nobody looks for.
  const parsed = parseTenantFeatures({
    real: true,
    off: false,
    stringy: 'true',
    no: 'no',
    numeric: 1,
    nested: { enabled: true },
    listy: ['true'],
    nulled: null,
  })
  assert.deepEqual(parsed, { real: true, off: false })
  assert.equal(isFeatureEnabled(parsed, 'stringy'), false)
  assert.equal(isFeatureEnabled(parsed, 'numeric'), false)
})

test('a malformed features column is no features rather than a crash', () => {
  for (const raw of [null, undefined, 'features', 42, ['beta'], true]) {
    assert.deepEqual(parseTenantFeatures(raw), NO_TENANT_FEATURES)
  }
})

test('an empty features object is a valid answer', () => {
  assert.deepEqual(parseTenantFeatures({}), {})
})
