export interface Tenant {
  id: string
  slug: string
  name: string
  plan: string
  settings: Record<string, unknown>
}

export interface TenantContextValue {
  tenant: Tenant | null
  isLoading: boolean
}

export function getTenantFromHostname(hostname: string): string | null {
  // Extract subdomain as tenant slug: acme.product.com → acme
  const parts = hostname.split('.')
  return parts.length >= 3 ? parts[0] : null
}
