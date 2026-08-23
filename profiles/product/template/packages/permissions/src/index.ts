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
