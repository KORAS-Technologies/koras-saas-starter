import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  NO_PRODUCT_ACCESS,
  PRODUCT_PERMISSIONS,
  ROLE_PERMISSIONS,
  hasPermissions,
  isProductPermission,
  productAccessFromOrganizationRoles,
} from './index.js'

/**
 * Who may do what inside this product.
 *
 * These live in the generated product rather than in the starter because the
 * code does, and because they are the only executable statement of an argument
 * that is otherwise only in prose: navigation hiding is not authorization, and
 * the thing that decides both is this one function.
 */

test('an unrecognised role name grants nothing', () => {
  // The session cookie is signed by this application, which proves it minted
  // the cookie -- not that the names inside it are ones this build still
  // recognises. A platform role arriving in a product token lands here.
  const access = productAccessFromOrganizationRoles(['platform_super_admin', 'wizard'])
  assert.deepEqual(access, NO_PRODUCT_ACCESS)
  assert.equal(access.granted, false)
  assert.equal(hasPermissions(access, ['product.access']), false)
})

test('no roles at all grants nothing', () => {
  assert.equal(productAccessFromOrganizationRoles([]).granted, false)
})

test('a plain member may open the product and nothing else', () => {
  const access = productAccessFromOrganizationRoles(['member'])
  assert.equal(access.granted, true)
  assert.equal(access.role, 'product_member')
  assert.deepEqual(access.permissions, ['product.access'])
  assert.equal(hasPermissions(access, ['team.read']), false)
  assert.equal(hasPermissions(access, ['settings.manage']), false)
})

test('an owner and an administrator are product administrators', () => {
  for (const role of ['organization_owner', 'organization_admin'] as const) {
    const access = productAccessFromOrganizationRoles([role])
    assert.equal(access.role, 'product_admin', role)
    assert.equal(hasPermissions(access, ['team.manage', 'settings.manage']), true, role)
  }
})

test('scoped authorities read but do not manage', () => {
  // billing_admin and security_admin sound senior. Authority over spend and
  // authority over security policy are not authority over who may use a
  // product, and granting them team.manage because of how they sound is how a
  // scoped role quietly becomes a general one.
  for (const role of ['billing_admin', 'security_admin'] as const) {
    const access = productAccessFromOrganizationRoles([role])
    assert.equal(access.role, 'product_member', role)
    assert.equal(hasPermissions(access, ['team.manage']), false, role)
    assert.equal(hasPermissions(access, ['settings.manage']), false, role)
    assert.equal(hasPermissions(access, ['settings.read']), true, role)
  }
})

test('several roles union their permissions and take the strongest product role', () => {
  const access = productAccessFromOrganizationRoles(['member', 'organization_admin'])
  assert.equal(access.role, 'product_admin')
  assert.equal(hasPermissions(access, [...PRODUCT_PERMISSIONS]), true)
})

test('permissions come back sorted, so two equal authorities compare equal', () => {
  const first = productAccessFromOrganizationRoles(['security_admin', 'billing_admin'])
  const second = productAccessFromOrganizationRoles(['billing_admin', 'security_admin'])
  assert.deepEqual(first.permissions, second.permissions)
  assert.deepEqual([...first.permissions], [...first.permissions].sort())
})

test('an empty requirement is satisfied by any granted access', () => {
  const access = productAccessFromOrganizationRoles(['member'])
  assert.equal(hasPermissions(access, []), true)
  assert.equal(hasPermissions(access, undefined), true)
  // But never by an access that was not granted. A module with no declared
  // permission still requires the caller to be allowed in the product.
  assert.equal(hasPermissions(NO_PRODUCT_ACCESS, []), false)
})

test('every role decides every permission it holds', () => {
  for (const [role, permissions] of Object.entries(ROLE_PERMISSIONS)) {
    for (const permission of permissions) {
      assert.equal(isProductPermission(permission), true, role + ' grants ' + permission)
    }
  }
})

test('every role can open the product', () => {
  // A recognised role that cannot open the product is a role the middleware
  // admits and every page then refuses -- a 403 loop with no way out.
  for (const permissions of Object.values(ROLE_PERMISSIONS)) {
    assert.ok(permissions.includes('product.access'))
  }
})
