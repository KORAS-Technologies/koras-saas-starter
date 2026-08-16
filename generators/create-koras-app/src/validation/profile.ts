import { isValidProfile, listProfiles } from '../profiles/index.js'

export interface ProfileValidation {
  valid: boolean
  error?: string
}

export function validateProfile(profile: string): ProfileValidation {
  if (!profile) {
    return {
      valid: false,
      error: [
        '--profile is required in non-interactive mode.',
        `  Available profiles: ${listProfiles().join(', ')}`,
        '  Example: pnpm create-koras-app myapp --profile product',
      ].join('\n'),
    }
  }
  if (!isValidProfile(profile)) {
    return {
      valid: false,
      error: [
        `Unknown profile "${profile}".`,
        `  Available profiles: ${listProfiles().join(', ')}`,
        '  Run: pnpm create-koras-app --list-profiles',
      ].join('\n'),
    }
  }
  return { valid: true }
}
