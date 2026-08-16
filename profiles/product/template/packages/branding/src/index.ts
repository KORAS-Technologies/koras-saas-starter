export interface BrandingTokens {
  primaryColor: string
  secondaryColor: string
  logoUrl: string
  faviconUrl: string
  fontFamily: string
}

export const defaultBranding: BrandingTokens = {
  primaryColor: '#0f172a',
  secondaryColor: '#3b82f6',
  logoUrl: '/logo.svg',
  faviconUrl: '/favicon.ico',
  fontFamily: 'Inter, sans-serif',
}

export function mergeBranding(
  base: BrandingTokens,
  overrides: Partial<BrandingTokens>,
): BrandingTokens {
  return { ...base, ...overrides }
}
