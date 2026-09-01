/**
 * Organization roles.
 *
 * The same closed set the Python side defines in `koras_platform.roles`. They
 * are duplicated rather than shared because the two runtimes cannot import each
 * other, which makes drift the risk: a role added on one side and forgotten on
 * the other is a silent authorisation gap.
 *
 * There are deliberately no platform roles here. Those are KORAS staff
 * authority, they are defined by the Control Plane, and a product that can name
 * them is a product that can accidentally honour one that arrives in a token.
 */

export const ORGANIZATION_ROLES = [
  'organization_owner',
  'organization_admin',
  'billing_admin',
  'security_admin',
  'member',
] as const

export type OrganizationRole = (typeof ORGANIZATION_ROLES)[number]

export function isOrganizationRole(value: string): value is OrganizationRole {
  return (ORGANIZATION_ROLES as readonly string[]).includes(value)
}

/**
 * Roles admitted to the internal operations application.
 *
 * Listed explicitly rather than ranked. A hierarchy invites "at least admin"
 * comparisons that widen silently the moment a role is inserted into the middle
 * of the ordering — and the role that gets inserted is usually the new one
 * nobody has thought about yet.
 *
 * `billing_admin` and `security_admin` are absent on purpose. They are scoped
 * authorities within an organization, not general operator access.
 */
export const ADMIN_ROLES = ['organization_owner', 'organization_admin'] as const

export function canAdminister(roles: readonly string[]): boolean {
  return roles.some((role) => (ADMIN_ROLES as readonly string[]).includes(role))
}

/** Whether a caller holds any recognised role at all. */
export function hasAnyRole(roles: readonly string[]): boolean {
  return roles.some(isOrganizationRole)
}

/* -------------------------------------------------------------------------- */
/* Product permissions                                                        */
/* -------------------------------------------------------------------------- */

/**
 * What a caller may do inside this product.
 *
 * Five, because five is what the routes this repository actually ships check.
 * A permission with nothing behind it is a string that reads like a boundary
 * and enforces nothing, which is worse than an absent one -- somebody will
 * eventually write `requiredPermissions: ['reports.read']` against it and
 * believe the route is guarded.
 *
 * This vocabulary is **product-local**. It says nothing about platform
 * authority, which belongs to the Control Plane, and it creates no grant store:
 * every permission is derived from the organization role the verified session
 * already carries. Adding one is a line here plus a line in ROLE_PERMISSIONS,
 * in this repository, which is the product's own.
 *
 * The type is derived from the array rather than written out, so a typo in a
 * navigation module or a route guard fails to compile instead of silently
 * matching nothing and hiding a link forever.
 */
export const PRODUCT_PERMISSIONS = [
  /** May open this product at all. Held by every recognised role. */
  'product.access',
  'team.read',
  'team.manage',
  'settings.read',
  'settings.manage',
] as const

export type ProductPermission = (typeof PRODUCT_PERMISSIONS)[number]

export function isProductPermission(value: string): value is ProductPermission {
  return (PRODUCT_PERMISSIONS as readonly string[]).includes(value)
}

/**
 * Which permissions each organization role carries.
 *
 * A map rather than a ladder, for the reason ADMIN_ROLES already gives: a
 * hierarchy invites "at least admin" comparisons that widen the moment a role
 * is inserted into the middle of the ordering, and the role that gets inserted
 * is usually the new one nobody has thought about yet.
 *
 * `billing_admin` and `security_admin` read but do not manage. They are scoped
 * authorities within an organization -- the one over spend, the other over
 * security policy -- and neither of those is authority over who may use a
 * product. Granting them `team.manage` because they sound senior is how a
 * scoped role quietly becomes a general one.
 *
 * Typed as a total record, so adding a role to ORGANIZATION_ROLES without
 * deciding what it may do fails to compile rather than granting nothing in
 * silence.
 */
export const ROLE_PERMISSIONS: Record<OrganizationRole, readonly ProductPermission[]> = {
  organization_owner: PRODUCT_PERMISSIONS,
  organization_admin: PRODUCT_PERMISSIONS,
  security_admin: ['product.access', 'team.read', 'settings.read'],
  billing_admin: ['product.access', 'settings.read'],
  member: ['product.access'],
}

/**
 * A caller's role *within this product*, as distinct from their role in the
 * organization.
 *
 * One person may be an administrator of one product and a plain member of
 * another; the organization role is what they are to the customer, and this is
 * what they are to this application.
 */
export const PRODUCT_ROLES = ['product_admin', 'product_member'] as const

export type ProductRole = (typeof PRODUCT_ROLES)[number]

export interface ProductAccess {
  /** False means this caller may not use the product at all. */
  granted: boolean
  role: ProductRole | null
  permissions: readonly ProductPermission[]
}

/** Nothing. Returned rather than null so callers need no branch. */
export const NO_PRODUCT_ACCESS: ProductAccess = {
  granted: false,
  role: null,
  permissions: [],
}

/**
 * The one place product access is decided, and the seam a real assignment store
 * replaces.
 *
 * There is no per-product grant table today, and inventing one is not a small
 * change: it means new tables, a new API surface, and an authority the Control
 * Plane does not know about -- which is the thing `koras-profile-product` rule 6
 * exists to prevent. So access derives from the organization role the verified
 * session already carries:
 *
 *   organization_owner, organization_admin  ->  product_admin
 *   member, billing_admin, security_admin   ->  product_member
 *   nothing recognised                      ->  not granted
 *
 * When a product does grow per-product assignments -- rows saying this user may
 * open this product as this role -- this function's body is what changes, and
 * nothing that calls it does. Read the assignment, fall back to this derivation
 * for a user with no row, and return the same shape.
 *
 * Roles are re-checked against the closed set rather than trusted. The session
 * cookie is signed by this application, which proves it minted the cookie and
 * not that the names inside it are ones this build still recognises.
 */
export function productAccessFromOrganizationRoles(roles: readonly string[]): ProductAccess {
  const recognised = roles.filter(isOrganizationRole)
  if (recognised.length === 0) return NO_PRODUCT_ACCESS

  const permissions = new Set<ProductPermission>()
  for (const role of recognised) {
    for (const permission of ROLE_PERMISSIONS[role]) permissions.add(permission)
  }

  return {
    granted: true,
    role: canAdminister(recognised) ? 'product_admin' : 'product_member',
    // Sorted so two callers with the same authority produce the same value,
    // which is what makes this comparable in a test and stable in a log line.
    permissions: [...permissions].sort(),
  }
}

/** Whether an access holds every permission named. An empty list is satisfied. */
export function hasPermissions(
  access: ProductAccess,
  required: readonly ProductPermission[] | undefined,
): boolean {
  if (!access.granted) return false
  if (required === undefined || required.length === 0) return true
  return required.every((permission) => access.permissions.includes(permission))
}
