import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'

const PROFILES_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../../profiles')

/**
 * The environments a service declares in services/<dir>/service.yaml, or null
 * for "every configured environment" -- which is also what a service with no
 * descriptor means.
 *
 * Only the environment list is read here, and only to name apps accurately in
 * the README. This is NOT the rule that decides what exists: the deploy
 * workflow (local/scripts/service-descriptor.sh) and the Terraform module
 * (modules/fly/eligibility) decide that, strictly, and a test holds them to the same
 * answers. A descriptor this does not understand throws rather than guessing.
 */
export function declaredEnvironments(profile: string, serviceKey: string): string[] | null {
  const dir = serviceKey.replace(/_/g, '-')
  for (const layer of [profile, '_shared']) {
    const file = join(PROFILES_ROOT, layer, 'template', 'services', dir, 'service.yaml')
    if (!existsSync(file)) continue
    const doc = yaml.load(readFileSync(file, 'utf8')) as Record<string, unknown> | null
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
      throw new Error(`${file}: not a mapping`)
    }
    if (!('environments' in doc)) return null
    const envs = doc.environments
    if (!Array.isArray(envs) || envs.length === 0 || envs.some((e) => typeof e !== 'string')) {
      throw new Error(`${file}: environments must be a non-empty list of names`)
    }
    return envs as string[]
  }
  return null
}
