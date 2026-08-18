import { allInputs, resolveTerraformEnv } from 'create-koras-app/terraform'

/**
 * Environment access for the checks.
 *
 * The list of required bootstrap secrets is not redeclared here. It lives in
 * the generator's Terraform input registry — the same list `--provision`
 * preflights against — so the doctor cannot drift from what a bootstrap
 * actually needs. `resolveTerraformEnv` also collapses the uppercase Doppler
 * aliases (`TF_VAR_GITHUB_ORG`) onto the case-sensitive names Terraform reads
 * (`TF_VAR_github_org`), so a check can read one canonical name and accept both.
 */

export const BOOTSTRAP_DOPPLER_PROJECT = 'koras-platform-bootstrap'
export const BOOTSTRAP_DOPPLER_CONFIG = 'prod'

/** Normalizes aliases and assembles composite values, once per run. */
export function resolveEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return resolveTerraformEnv(env)
}

/** A value that is present and not blank. Blank is treated as absent. */
export function value(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name]
  return raw !== undefined && raw.trim() !== '' ? raw.trim() : undefined
}

export interface RequiredValues {
  ok: boolean
  missing: string[]
  values: Record<string, string>
}

/**
 * Reads several required values at once.
 *
 * `display` maps a canonical name to the name an operator stores in Doppler,
 * so the failure text names the key they actually have to fix.
 */
export function require(
  env: NodeJS.ProcessEnv,
  names: readonly string[],
  display: Record<string, string> = {},
): RequiredValues {
  const values: Record<string, string> = {}
  const missing: string[] = []

  for (const name of names) {
    const found = value(env, name)
    if (found === undefined) missing.push(display[name] ?? name)
    else values[name] = found
  }

  return { ok: missing.length === 0, missing, values }
}

/** Every bootstrap secret the generator's provisioning path requires. */
export function requiredBootstrapKeys(): string[] {
  return allInputs().map((input) => input.alias ?? input.name)
}

/**
 * Bootstrap keys that cannot be resolved from this environment, reported under
 * the name Doppler stores. Composite values (the ZITADEL and Supabase maps)
 * count as present when their flat per-environment parts are.
 */
export function missingBootstrapKeys(env: NodeJS.ProcessEnv): string[] {
  const resolved = resolveEnv(env)
  return allInputs()
    .filter((input) => value(resolved, input.name) === undefined)
    .map((input) => input.alias ?? input.name)
}
