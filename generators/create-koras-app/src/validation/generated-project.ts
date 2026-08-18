import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
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

  return { valid: true, manifest }
}
