import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'
import { z } from 'zod'
import type { GenerationContext } from './context.js'
import { listProfiles, isValidProfile } from '../profiles/loader.js'

/**
 * The KORAS project manifest — `.koras/project.yaml`.
 *
 * Every generated repository carries one, whatever its profile. It is the
 * authoritative answer to "which starter generated this repository, under which
 * profile, at which versions" — previously only inferable from
 * `infrastructure/terraform/terraform.tfvars`, which is a provisioning input
 * rather than an identity record.
 *
 * This is a stable platform contract. Future tooling (`koras doctor`,
 * `koras upgrade`, `koras diff-starter`, `koras project:info`, and Control
 * Plane registration) reads it, so `schema_version` is not to be changed
 * without an explicit migration design.
 *
 * References only — no secrets, no credentials, no endpoints. The file is
 * safe to commit, and the generated `.gitignore` deliberately does not exclude it.
 */

const STARTER_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..')

/** Canonical location, relative to the generated project root. */
export const PROJECT_MANIFEST_PATH = '.koras/project.yaml'

export const GENERATOR_NAME = 'create-koras-app'

/** Only bump alongside a manifest migration design. */
export const PROJECT_MANIFEST_SCHEMA_VERSION = 1

// ── Types ───────────────────────────────────────────────────────────────────

export type KorasProjectProfile = 'product' | 'control-plane'

export interface KorasProjectManifest {
  schema_version: typeof PROJECT_MANIFEST_SCHEMA_VERSION
  project: {
    name: string
    slug: string
    profile: KorasProjectProfile
  }
  generator: {
    name: typeof GENERATOR_NAME
    starter_version: string
    profile_version: string
  }
}

// ── Schema ──────────────────────────────────────────────────────────────────

// The official semver.org reference pattern. Versions reach the manifest from
// files a human edits, so they are validated rather than trusted.
const SEMVER_RE =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$/

export const semverSchema = z
  .string()
  .regex(SEMVER_RE, 'must be a semantic version, for example 1.0.0')

/**
 * Reusable schema — validation on write here, and the parser for any future
 * command that needs to read a generated project's manifest.
 */
export const KorasProjectManifestSchema = z.object({
  schema_version: z.literal(PROJECT_MANIFEST_SCHEMA_VERSION),
  project: z.object({
    name: z.string().min(1, 'must not be empty'),
    slug: z.string().min(1, 'must not be empty'),
    profile: z.enum(['product', 'control-plane']),
  }),
  generator: z.object({
    name: z.literal(GENERATOR_NAME),
    starter_version: semverSchema,
    profile_version: semverSchema,
  }),
})

// ── Version resolution ──────────────────────────────────────────────────────

/**
 * Version of the KORAS SaaS Starter that generated the project, read from the
 * workspace root `package.json` — the repository's single canonical version.
 *
 * Read at generation time rather than baked in at build time, so a locally
 * built generator reports the tree it actually came from. There is deliberately
 * no fallback: a manifest claiming "unknown" would be worse than a failed
 * generation, because downstream tooling would trust it.
 */
export function resolveStarterVersion(): string {
  const pkgPath = join(STARTER_ROOT, 'package.json')
  let pkg: { name?: unknown; version?: unknown }
  try {
    pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as typeof pkg
  } catch (err) {
    throw new Error(
      `Could not resolve the starter version from ${pkgPath}: ${String(err)}\n` +
        '  The generator writes this into every project\'s .koras/project.yaml.',
    )
  }

  const version = pkg.version
  if (typeof version !== 'string' || !SEMVER_RE.test(version)) {
    throw new Error(
      `The starter version in ${pkgPath} is not a semantic version ` +
        `(found: ${JSON.stringify(version)}).\n` +
        '  Fix the root package.json "version" field before generating.',
    )
  }
  return version
}

/**
 * Version of the selected profile, read from its manifest. Independent of the
 * starter version: a starter fix ships without touching profile behaviour,
 * while a breaking profile structure change bumps this.
 */
export function resolveProfileVersion(ctx: GenerationContext): string {
  const version = ctx.manifest.version
  if (!SEMVER_RE.test(version)) {
    throw new Error(
      `Profile "${ctx.profile}" declares version "${version}", which is not a ` +
        'semantic version.\n' +
        `  Fix the "version" field in profiles/${ctx.profile}/manifest.yaml.`,
    )
  }
  return version
}

// ── Construction, validation, serialization ─────────────────────────────────

export function buildProjectManifest(ctx: GenerationContext): KorasProjectManifest {
  // A profile that is not one of the supported set must never reach a written
  // manifest — Control Plane tooling gates on this field before it provisions.
  if (!isValidProfile(ctx.profile)) {
    throw new Error(
      `Cannot write ${PROJECT_MANIFEST_PATH}: unsupported profile ` +
        `"${String(ctx.profile)}".\n` +
        `  Supported profiles: ${listProfiles().join(', ')}`,
    )
  }

  // Key order is fixed here, and js-yaml preserves insertion order, so
  // serialization is deterministic for a given context.
  const manifest: KorasProjectManifest = {
    schema_version: PROJECT_MANIFEST_SCHEMA_VERSION,
    project: {
      name: ctx.projectName,
      slug: ctx.projectSlug,
      profile: ctx.profile,
    },
    generator: {
      name: GENERATOR_NAME,
      starter_version: resolveStarterVersion(),
      profile_version: resolveProfileVersion(ctx),
    },
  }

  return validateProjectManifest(manifest, 'generated')
}

/** Throws with the failing field paths rather than writing an invalid manifest. */
export function validateProjectManifest(value: unknown, source: string): KorasProjectManifest {
  const result = KorasProjectManifestSchema.safeParse(value)
  if (!result.success) {
    const issues = result.error.issues.map((i) => `  ${i.path.join('.')}: ${i.message}`).join('\n')
    throw new Error(`Invalid KORAS project manifest (${source}):\n${issues}`)
  }
  return result.data
}

/** Parses and validates a manifest read back from disk. */
export function parseProjectManifest(contents: string, source: string): KorasProjectManifest {
  let raw: unknown
  try {
    raw = yaml.load(contents)
  } catch (err) {
    throw new Error(`${source} is not valid YAML: ${String(err)}`)
  }
  return validateProjectManifest(raw, source)
}

export function serializeProjectManifest(manifest: KorasProjectManifest): string {
  const header =
    '# KORAS project manifest — generated by create-koras-app.\n' +
    '# Identifies this repository to KORAS tooling. Safe to commit: it holds\n' +
    '# references only, never secrets. Regenerate rather than editing by hand.\n'
  // `sortKeys` is left off so the emitted order matches the declared shape:
  // schema_version, project, generator. `lineWidth: -1` disables line folding.
  return header + yaml.dump(manifest, { lineWidth: -1, noRefs: true, sortKeys: false })
}

export function renderProjectManifest(ctx: GenerationContext): string {
  return serializeProjectManifest(buildProjectManifest(ctx))
}
