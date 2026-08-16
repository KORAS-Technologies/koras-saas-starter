import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'
import {
  ProfileManifestSchema,
  ProfileDefaultsSchema,
  type LoadedProfile,
  type ProfileManifest,
  type ProfileDefaults,
} from './types.js'

const PROFILES_DIR = join(dirname(fileURLToPath(import.meta.url)), '../../../../profiles')

const VALID_PROFILES = ['product', 'control-plane'] as const
export type ProfileName = (typeof VALID_PROFILES)[number]

export function isValidProfile(name: string): name is ProfileName {
  return (VALID_PROFILES as readonly string[]).includes(name)
}

export function listProfiles(): ProfileName[] {
  return [...VALID_PROFILES]
}

export function loadProfile(profileName: ProfileName): LoadedProfile {
  const profileDir = join(PROFILES_DIR, profileName)
  const manifest = loadManifest(profileDir, profileName)
  const defaults = loadDefaults(profileDir, profileName)
  return { manifest, defaults }
}

function loadManifest(profileDir: string, profileName: string): ProfileManifest {
  const manifestPath = join(profileDir, 'manifest.yaml')
  let raw: unknown
  try {
    raw = yaml.load(readFileSync(manifestPath, 'utf8'))
  } catch (err) {
    throw new Error(
      `Failed to read manifest for profile "${profileName}" at ${manifestPath}: ${String(err)}`,
    )
  }

  const result = ProfileManifestSchema.safeParse(raw)
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `  ${i.path.join('.')}: ${i.message}`)
      .join('\n')
    throw new Error(`Invalid manifest for profile "${profileName}":\n${issues}`)
  }

  if (result.data.profile !== profileName) {
    throw new Error(
      `Manifest profile field "${result.data.profile}" does not match directory name "${profileName}"`,
    )
  }

  return result.data
}

function loadDefaults(profileDir: string, profileName: string): ProfileDefaults {
  const defaultsPath = join(profileDir, 'defaults.yaml')
  let raw: unknown
  try {
    raw = yaml.load(readFileSync(defaultsPath, 'utf8'))
  } catch (err) {
    throw new Error(
      `Failed to read defaults for profile "${profileName}" at ${defaultsPath}: ${String(err)}`,
    )
  }

  const result = ProfileDefaultsSchema.safeParse(raw)
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `  ${i.path.join('.')}: ${i.message}`)
      .join('\n')
    throw new Error(`Invalid defaults for profile "${profileName}":\n${issues}`)
  }

  return result.data
}
