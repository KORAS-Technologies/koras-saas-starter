/**
 * Post-apply extraction of infrastructure references.
 *
 * Only non-secret references are read. Terraform marks sensitive outputs in
 * `terraform output -json`; any such output is dropped here rather than
 * carried into logs or the Control Plane registration payload (Phase 10).
 */

export interface TerraformOutputValue {
  value: unknown
  sensitive?: boolean
  type?: unknown
}

export interface EnvironmentReferences {
  environment: string
  dopplerProject: string
  supabaseProject: string
  flyApps: string[]
}

export interface ProvisionOutputs {
  githubRepository: string
  githubRepositoryUrl: string
  dopplerProject: string
  supabaseProjectRefs: Record<string, string>
  zitadelProjectIds: Record<string, string>
  /**
   * The organization each ZITADEL project lives in.
   *
   * Carried beside the project ids rather than looked up, because it cannot be
   * looked up: a management-API call acts in the organization of whoever holds
   * the token unless told otherwise, and this estate has more than one.
   */
  zitadelOrgIds: Record<string, string>
  /** Base URL of the ZITADEL instance each environment uses. */
  zitadelDomains: Record<string, string>
  vercelProjectIds: Record<string, string>
  flyApps: string[]
  /**
   * Upstash database ids, keyed by environment.
   *
   * Ids rather than endpoints, because the delete API takes an id. Teardown
   * read a field the module never exported and therefore found no Upstash at
   * all -- reporting a complete run while four databases stayed alive. An
   * output nobody parses and a parser field nobody exports look identical from
   * either side.
   */
  redisDatabaseIds: Record<string, string>
  /** Outputs Terraform marked sensitive, recorded by name only. */
  withheld: string[]
}

export function parseTerraformOutputs(json: string): ProvisionOutputs {
  let raw: Record<string, TerraformOutputValue>
  try {
    raw = JSON.parse(json) as Record<string, TerraformOutputValue>
  } catch (err) {
    throw new Error(`Could not parse \`terraform output -json\`: ${String(err)}`)
  }

  // Every sensitive output is withheld, whether or not this parser reads it —
  // an unread secret is still a secret the operator should know exists.
  const withheld = Object.entries(raw)
    .filter(([, entry]) => entry?.sensitive === true)
    .map(([name]) => name)
    .sort()

  const read = (name: string): unknown => {
    const entry = raw[name]
    if (entry === undefined || entry.sensitive) return undefined
    return entry.value
  }

  const asString = (name: string): string => {
    const value = read(name)
    return typeof value === 'string' ? value : ''
  }

  const asStringMap = (name: string): Record<string, string> => {
    const value = read(name)
    if (value === null || typeof value !== 'object') return {}
    const result: Record<string, string> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (typeof v === 'string') result[k] = v
    }
    return result
  }

  const flyAppNames = asStringMap('fly_app_names')

  return {
    githubRepository: asString('github_repository_full_name'),
    githubRepositoryUrl: asString('github_repository_url'),
    dopplerProject: asString('doppler_project_name'),
    supabaseProjectRefs: asStringMap('supabase_project_refs'),
    zitadelProjectIds: asStringMap('zitadel_project_ids'),
    zitadelOrgIds: asStringMap('zitadel_resolved_org_ids'),
    zitadelDomains: asStringMap('zitadel_domains'),
    vercelProjectIds: asStringMap('vercel_project_ids'),
    flyApps: Object.values(flyAppNames).sort(),
    redisDatabaseIds: asStringMap('redis_database_ids'),
    withheld,
  }
}

/** Groups references by environment for the Phase 10 registration payload. */
export function groupByEnvironment(
  outputs: ProvisionOutputs,
  projectSlug: string,
  environments: string[],
): EnvironmentReferences[] {
  return environments.map((environment) => ({
    environment,
    dopplerProject: `${projectSlug}-${environment}`,
    supabaseProject: outputs.supabaseProjectRefs[environment] ?? `${projectSlug}-${environment}`,
    flyApps: outputs.flyApps.filter((app) => app.endsWith(`-${environment}`)),
  }))
}

export function formatOutputs(outputs: ProvisionOutputs): string {
  const lines = [
    '',
    'Provisioned infrastructure:',
    `  GitHub:    ${outputs.githubRepository || '(none)'}`,
    `  Doppler:   ${outputs.dopplerProject || '(none)'}`,
    `  Supabase:  ${Object.values(outputs.supabaseProjectRefs).join(', ') || '(none)'}`,
    `  ZITADEL:   ${Object.keys(outputs.zitadelProjectIds).join(', ') || '(none)'}`,
    `  Vercel:    ${Object.keys(outputs.vercelProjectIds).join(', ') || '(none)'}`,
    `  Fly.io:    ${outputs.flyApps.join(', ') || '(none)'}`,
  ]

  if (outputs.withheld.length > 0) {
    lines.push('', `  ${outputs.withheld.length} sensitive output(s) withheld: ${outputs.withheld.join(', ')}`)
  }

  return lines.join('\n')
}
