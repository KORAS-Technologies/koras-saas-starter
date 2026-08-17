/**
 * Checks that the HCP Terraform workspace is set to *local* execution.
 *
 * With the `remote` backend, a workspace defaults to Remote execution: HCP
 * uploads the configuration and runs Terraform on its own servers. That cannot
 * work here — credentials are injected locally by Doppler and HCP would never
 * see them — and it also forbids `plan -out`, which the approval gate depends
 * on so that the plan an operator approves is exactly the plan that applies.
 *
 * Remote execution therefore fails late and confusingly. This catches it
 * before `plan` runs.
 */

export interface BackendConfig {
  organization: string
  workspace: string
}

/** Extracts the organization and workspace from a rendered backend.tf. */
export function readBackendConfig(contents: string): BackendConfig | undefined {
  if (!/backend\s+"remote"/.test(contents)) return undefined

  const organization = /organization\s*=\s*"([^"]+)"/.exec(contents)?.[1]
  const workspace = /workspaces\s*\{[^}]*name\s*=\s*"([^"]+)"/s.exec(contents)?.[1]

  return organization && workspace ? { organization, workspace } : undefined
}

export type ExecutionModeResult =
  | { status: 'local' }
  | { status: 'remote'; message: string }
  /** Not determinable — a missing token, a new workspace, or an offline run. */
  | { status: 'unknown'; reason: string }

export type FetchLike = (url: string, init?: { headers?: Record<string, string> }) => Promise<{
  ok: boolean
  status: number
  json: () => Promise<unknown>
}>

export async function checkExecutionMode(
  backend: BackendConfig,
  token: string | undefined,
  fetchImpl: FetchLike = fetch as unknown as FetchLike,
): Promise<ExecutionModeResult> {
  if (!token) return { status: 'unknown', reason: 'no HCP Terraform token in the environment' }

  const url =
    `https://app.terraform.io/api/v2/organizations/${encodeURIComponent(backend.organization)}` +
    `/workspaces/${encodeURIComponent(backend.workspace)}`

  let body: unknown
  try {
    const response = await fetchImpl(url, {
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/vnd.api+json' },
    })
    // A workspace that does not exist yet is created by `init`; nothing to check.
    if (response.status === 404) return { status: 'unknown', reason: 'workspace does not exist yet' }
    if (!response.ok) return { status: 'unknown', reason: `HCP API returned ${response.status}` }
    body = await response.json()
  } catch (err) {
    return { status: 'unknown', reason: `could not reach HCP Terraform: ${String(err)}` }
  }

  const mode = (body as { data?: { attributes?: Record<string, unknown> } })?.data?.attributes?.[
    'execution-mode'
  ]

  if (mode === 'local') return { status: 'local' }
  if (typeof mode !== 'string') return { status: 'unknown', reason: 'execution mode not reported' }

  return {
    status: 'remote',
    message: [
      `Workspace "${backend.workspace}" in organization "${backend.organization}" runs in`,
      `${mode} execution mode. It must be local.`,
      '',
      '  Remote execution runs Terraform on HCP servers, where the credentials',
      '  Doppler injects locally do not exist — and it forbids saving a plan,',
      '  which the approval gate needs so that the approved plan is the one applied.',
      '',
      '  Fix: HCP Terraform → the workspace → Settings → General →',
      '       Execution Mode → Local → Save.',
      '',
      `  https://app.terraform.io/app/${backend.organization}/workspaces/${backend.workspace}/settings/general`,
    ].join('\n'),
  }
}
