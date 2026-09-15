import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import {
  CLAUDE_CONFIG_PATHS,
  PRODUCT_ORCHESTRATION_PATHS,
  PROFILE_CARRIES_ORCHESTRATION,
  claudeProfileSkillPath,
} from './claude-config.js'
import {
  PROJECT_MANIFEST_PATH,
  parseProjectManifest,
  type KorasProjectManifest,
} from '../generation/project-manifest.js'

/**
 * Post-write validation of a generated repository.
 *
 * The manifest is read back from disk rather than trusted from memory: the
 * point is to prove that what landed on disk is what downstream tooling will
 * read. `koras doctor`, `koras upgrade`, and Control Plane registration all
 * gate on this file, and a project whose manifest disagrees with the requested
 * profile is more dangerous than one with no manifest at all.
 */

export interface GeneratedProjectValidation {
  valid: boolean
  /** Actionable message, present when `valid` is false. */
  error?: string
  manifest?: KorasProjectManifest
}

export function validateGeneratedProject(params: {
  projectRoot: string
  expectedSlug: string
  expectedProfile: string
}): GeneratedProjectValidation {
  const { projectRoot, expectedSlug, expectedProfile } = params
  const manifestPath = join(projectRoot, PROJECT_MANIFEST_PATH)

  if (!existsSync(manifestPath)) {
    return {
      valid: false,
      error:
        `The generated project has no ${PROJECT_MANIFEST_PATH}.\n` +
        `  Expected at: ${manifestPath}\n` +
        '  KORAS tooling identifies a project by this file; generation is incomplete without it.',
    }
  }

  let manifest: KorasProjectManifest
  try {
    // Covers "valid YAML", "supported schema_version", and the presence and
    // shape of both versions — all enforced by KorasProjectManifestSchema.
    manifest = parseProjectManifest(readFileSync(manifestPath, 'utf8'), PROJECT_MANIFEST_PATH)
  } catch (err) {
    return { valid: false, error: err instanceof Error ? err.message : String(err) }
  }

  // The profile check is the reason this validation exists. A control-plane
  // request that produced `profile: product` would let later tooling run
  // product provisioning against the platform authority.
  if (manifest.project.profile !== expectedProfile) {
    return {
      valid: false,
      manifest,
      error:
        `${PROJECT_MANIFEST_PATH} records profile "${manifest.project.profile}", ` +
        `but the project was generated with --profile ${expectedProfile}.`,
    }
  }

  if (manifest.project.slug !== expectedSlug) {
    return {
      valid: false,
      manifest,
      error:
        `${PROJECT_MANIFEST_PATH} records slug "${manifest.project.slug}", ` +
        `but the project was generated as "${expectedSlug}".`,
    }
  }

  // The Claude configuration is a generation output like any other, and its
  // absence is silent: a project missing `.claude/` still builds, still
  // deploys, and only misbehaves later when an agent works in it without the
  // repository's rules. Cheaper to fail here than to discover it in a diff.
  const claudeError = missingClaudeConfig(projectRoot, manifest.project.profile)
  if (claudeError !== undefined) return { valid: false, manifest, error: claudeError }

  return { valid: true, manifest }
}

/**
 * The common Claude configuration reaches a project as a shared asset and the
 * profile skill as a template file — two different mechanisms, so both are
 * checked. The profile skill is checked by name rather than by presence of
 * *some* skill: a control-plane project carrying the product skill is the
 * failure this exists to catch.
 */
function missingClaudeConfig(projectRoot: string, profile: string): string | undefined {
  const carriesOrchestration = PROFILE_CARRIES_ORCHESTRATION[profile] === true

  const required = [
    ...CLAUDE_CONFIG_PATHS,
    claudeProfileSkillPath(profile),
    ...(carriesOrchestration ? PRODUCT_ORCHESTRATION_PATHS : []),
  ]
  const missing = required.filter((path) => !existsSync(join(projectRoot, path)))
  if (missing.length > 0) {
    return [
      'The generated project is missing its Claude Code configuration:',
      ...missing.map((path) => `  ${path}`),
      '  The common tree is a shared_asset (`.claude`) declared in ' +
        `profiles/${profile}/manifest.yaml;`,
      `  the profile skill and the orchestration framework are template-owned at`,
      `  profiles/${profile}/template/.claude/.`,
    ].join('\n')
  }

  // The other direction, and the one that fails quietly. `.claude` is copied
  // verbatim into both profiles, so anything that leaked into the shared tree
  // reaches the Control Plane as well -- where a customer-product
  // orchestration contract looks entirely normal until an agent follows it.
  if (!carriesOrchestration) {
    const leaked = PRODUCT_ORCHESTRATION_PATHS.filter((path) =>
      existsSync(join(projectRoot, path)),
    )
    if (leaked.length > 0) {
      return [
        `A "${profile}" project carries the product multi-agent framework, which is product-only:`,
        ...leaked.map((path) => `  ${path}`),
        '  It must live in profiles/product/template/.claude/, never in the',
        '  starter root `.claude`, which is a shared_asset copied to both profiles.',
      ].join('\n')
    }
  }

  return undefined
}
