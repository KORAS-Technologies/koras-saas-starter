/**
 * The Claude Code configuration contract for a generated KORAS repository.
 *
 * Named here rather than inline in the validator because three places need the
 * same answer and must not drift: post-write validation, the generator tests,
 * and anything later that audits an existing project back into alignment.
 *
 * Two mechanisms deliver this configuration, and the split is deliberate:
 *
 *  - Everything common arrives as the `.claude` shared asset, copied verbatim
 *    from the starter. One definition, every repository.
 *  - The profile skill arrives from the profile's own template tree, so a
 *    product can never receive control-plane instructions and vice versa.
 *
 * This is not an inventory of every file. It is the set whose absence means
 * generation produced a repository an agent would work in without its rules —
 * the skills a project cannot function without, plus one command, one agent and
 * one external skill as proof the trees arrived rather than the directories.
 */

/** The twelve Koras skills every KORAS repository carries. */
export const KORAS_COMMON_SKILLS = [
  'koras-architecture',
  'koras-feature-development',
  'koras-ui-design-system',
  'koras-forms',
  'koras-api-client',
  'koras-auth',
  'koras-multitenancy',
  'koras-supabase',
  'koras-security',
  'koras-accessibility',
  'koras-testing',
  'koras-code-review',
] as const

/** Vendored, pinned in `.claude/external-skills.yaml`. */
export const EXTERNAL_SKILLS = [
  'frontend-design',
  'webapp-testing',
  'react-best-practices',
  'web-design-guidelines',
] as const

export const CLAUDE_COMMANDS = ['feature', 'review', 'test', 'ui-review'] as const

export const CLAUDE_AGENTS = ['architect', 'frontend', 'reviewer', 'tester'] as const

/** Profile name -> the one profile skill that profile's projects receive. */
export const CLAUDE_PROFILE_SKILLS: Record<string, string> = {
  product: 'koras-profile-product',
  'control-plane': 'koras-profile-control-plane',
}

export function claudeSkillPath(skill: string): string {
  return `.claude/skills/${skill}/SKILL.md`
}

/**
 * Throws rather than returning a path for an unknown profile: a project whose
 * profile has no declared skill would otherwise validate by checking nothing.
 */
export function claudeProfileSkillPath(profile: string): string {
  const skill = CLAUDE_PROFILE_SKILLS[profile]
  if (skill === undefined) {
    throw new Error(
      `No Claude profile skill is declared for profile "${profile}".\n` +
        `  Declared profiles: ${Object.keys(CLAUDE_PROFILE_SKILLS).join(', ')}`,
    )
  }
  return claudeSkillPath(skill)
}

/** Profile-independent paths every generated repository must carry. */
export const CLAUDE_CONFIG_PATHS: string[] = [
  '.claude/CLAUDE.md',
  '.claude/external-skills.yaml',
  ...KORAS_COMMON_SKILLS.map(claudeSkillPath),
  // One of each remaining tree. A directory that arrived empty is the failure
  // mode worth catching; enumerating all twenty-odd files would only make this
  // list something to update rather than something to trust.
  '.claude/commands/feature.md',
  '.claude/agents/reviewer.md',
  claudeSkillPath('react-best-practices'),
]
