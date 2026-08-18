/**
 * The bootstrap doctor answers exactly one question: are all required KORAS
 * bootstrap integrations configured and accessible?
 *
 * There are two outcomes and no third. No WARN, no SKIP: a check that cannot
 * run because its credentials are absent has not passed, and calling that
 * anything other than a failure would let a bootstrap start against an
 * integration nobody verified.
 */

export interface DoctorResult {
  passed: boolean
  /** Shown only on failure, and only after redaction. Never contains a value. */
  error?: string
}

export interface DoctorCheck {
  /** Row label. Display order is the order checks are declared. */
  label: string
  run: (ctx: DoctorContext) => Promise<DoctorResult>
}

/** Everything a check may touch. All of it is injectable, so tests reach no real system. */
export interface DoctorContext {
  env: NodeJS.ProcessEnv
  fetchImpl: FetchLike
  exec: CommandExecutor
  /** Repository root — the Terraform checks read modules from it. */
  repoRoot: string
}

export interface HttpResponse {
  ok: boolean
  status: number
  text: () => Promise<string>
}

export type FetchLike = (
  url: string,
  init?: {
    method?: string
    headers?: Record<string, string>
    body?: string
  },
) => Promise<HttpResponse>

export interface CommandResult {
  exitCode: number
  stdout: string
  stderr: string
}

export type CommandExecutor = (
  command: string,
  args: string[],
  options: { cwd: string; env: NodeJS.ProcessEnv },
) => Promise<CommandResult>
