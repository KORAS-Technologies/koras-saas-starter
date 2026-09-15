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

/**
 * The multi-agent engineering framework, which belongs to the product profile
 * alone.
 *
 * It cannot travel as part of the `.claude` shared asset: that directory is
 * copied verbatim and unconditionally into *both* profiles, so anything placed
 * there reaches the Control Plane too. It is template-owned at
 * `profiles/product/template/.claude/` instead — the same mechanism that keeps
 * the profile skills apart, and for the same reason.
 *
 * Both halves are asserted. A product missing the framework is a generation
 * failure; a Control Plane carrying it is the quieter one, and the one worth
 * catching — a Control Plane repository with a customer-product orchestration
 * contract in it looks entirely normal until an agent follows it.
 */
export const PRODUCT_ORCHESTRATION_PATHS = [
  '.claude/orchestration/agent-registry.yaml',
  '.claude/orchestration/activation-rules.yaml',
  '.claude/orchestration/workflow.yaml',
  '.claude/orchestration/quality-gates.yaml',
  '.claude/orchestration/documentation-policy.yaml',
  '.claude/orchestration/definition-of-done.md',
  '.claude/orchestration/WORKTREE-STANDARD.md',
  '.claude/AGENT-INVENTORY.md',
  '.claude/MASTER-PROMPT.md',
  // One agent from each end of the registry, and the domain contract. Proof
  // the trees arrived rather than the directories; the orchestration test is
  // what checks all forty.
  '.claude/agents/orchestration/engineering-orchestrator.md',
  '.claude/agents/development/developer-3.md',
  '.claude/agents/testing/manual-qa.md',
  '.claude/domain/DOMAIN-AGENT-TEMPLATE.md',
] as const

/** The three parallel implementation worker slots. Exactly three, by design. */
export const DEVELOPER_WORKERS = ['developer-1', 'developer-2', 'developer-3'] as const

/** Profile name -> orchestration framework expected, or expected absent. */
export const PROFILE_CARRIES_ORCHESTRATION: Record<string, boolean> = {
  product: true,
  'control-plane': false,
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
