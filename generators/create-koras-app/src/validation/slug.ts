const RESERVED = new Set([
  'koras', 'api', 'admin', 'www', 'mail', 'auth', 'app', 'portal',
  'platform', 'static', 'assets', 'cdn', 'localhost', 'test',
])

const SLUG_RE = /^[a-z][a-z0-9-]{0,48}[a-z0-9]$/

export interface SlugValidation {
  valid: boolean
  error?: string
  suggestion?: string
}

export function validateSlug(slug: string): SlugValidation {
  if (slug.length < 2) {
    return { valid: false, error: 'Slug must be at least 2 characters.' }
  }
  if (slug.length > 50) {
    return { valid: false, error: 'Slug must be 50 characters or fewer.' }
  }
  if (RESERVED.has(slug)) {
    return { valid: false, error: `"${slug}" is a reserved name.` }
  }
  if (!SLUG_RE.test(slug)) {
    const suggestion = slug
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
    return {
      valid: false,
      error: 'Slugs may only contain lowercase letters, digits, and hyphens.',
      suggestion: suggestion !== slug ? suggestion : undefined,
    }
  }
  if (slug.includes('--')) {
    return { valid: false, error: 'Slugs may not contain consecutive hyphens.' }
  }
  return { valid: true }
}

export function deriveSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}
