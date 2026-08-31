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
  /** Hostname -> Cloudflare DNS record id. */
  cloudflareRecordIds: Record<string, string>
  /** The zone those records live in; a record id is not addressable without it. */
  cloudflareZoneId: string
  vercelProjectIds: Record<string, string>
  /**
   * Environment -> the URL a customer of this product signs in at.
   *
   * Read from the apply rather than rebuilt here, though the two would agree
   * today: the Terraform computes `app-<env>.<primary domain>` and this could
   * too. Rebuilding it would put the same convention in two repositories, and
   * the copy that drifts is always the one further from the resource -- a
   * product that moves to a brand domain changes its Terraform, not this file.
   *
   * The Control Plane needs it because the welcome email has nowhere to point
   * without it. Absent for an estate applied before the output existed, which
   * is a missing link in an email rather than a failure.
   */
  appUrls: Record<string, string>
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
    cloudflareRecordIds: asStringMap('cloudflare_record_ids'),
    cloudflareZoneId: asString('cloudflare_zone_id'),
    vercelProjectIds: asStringMap('vercel_project_ids'),
    appUrls: asStringMap('app_urls'),
    flyApps: Object.values(flyAppNames).sort(),
    redisDatabaseIds: asStringMap('redis_database_ids'),
    withheld,
  }
}

/**
 * Whether these outputs describe any infrastructure at all.
 *
 * `terraform output -json` answers `{}` for a workspace that has never been
 * applied *and* for one that has been destroyed, and `parseTerraformOutputs`
 * turns that into a perfectly valid all-empty result rather than an error. So
 * "read the outputs and send them" cannot, on its own, tell an estate from an
 * absence.
 *
 * It matters because the payload built from an empty set is not obviously
 * wrong. Identity survives — code, name, slug, profile, primary domain and both
 * versions come from the manifest rather than from state — so the Control Plane
 * would accept it and answer 200, and the operator would be told the product
 * was registered. Nothing is destroyed by it: references are upserted per entry,
 * so empty maps write nothing and prune nothing. What is wrong is the claim.
 * The registry would be told a torn-down product is current, by a command whose
 * whole purpose is to make the registry match reality.
 *
 * Sensitive outputs are withheld by the parser, so `withheld` is checked too: a
 * state consisting entirely of secrets is a real estate, and reporting it as
 * empty would refuse a legitimate re-registration.
 */
export function describesInfrastructure(outputs: ProvisionOutputs): boolean {
  const strings = [
    outputs.githubRepository,
    outputs.githubRepositoryUrl,
    outputs.dopplerProject,
    outputs.cloudflareZoneId,
  ]
  const maps = [
    outputs.supabaseProjectRefs,
    outputs.zitadelProjectIds,
    outputs.zitadelOrgIds,
    outputs.zitadelDomains,
    outputs.cloudflareRecordIds,
    outputs.vercelProjectIds,
    outputs.redisDatabaseIds,
  ]
  return (
    strings.some((value) => value !== '') ||
    maps.some((map) => Object.keys(map).length > 0) ||
    outputs.flyApps.length > 0 ||
    outputs.withheld.length > 0
  )
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
