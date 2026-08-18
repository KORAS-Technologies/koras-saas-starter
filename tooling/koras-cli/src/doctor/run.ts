import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { CommandExecutor, DoctorCheck, DoctorContext, FetchLike } from './types.js'
import { resolveEnv } from './env.js'
import { redact } from './redact.js'
import { formatReport, exitCode, type ReportRow } from './report.js'
import { dopplerCheck } from './checks/doppler.js'
import { githubCheck } from './checks/github.js'
import { supabaseCheck } from './checks/supabase.js'
import { zitadelChecks } from './checks/zitadel.js'
import { vercelCheck } from './checks/vercel.js'
import { flyCheck } from './checks/fly.js'
import { cloudflareCheck } from './checks/cloudflare.js'
import { terraformCheck } from './checks/terraform.js'
import { terraformStateCheck } from './checks/terraform-state.js'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..')

/**
 * Display order is declaration order, and it is fixed.
 *
 * Every row is always reported, even when an earlier check failed. A run where
 * Doppler is broken still shows twelve rows, because "we could not tell" and
 * "it is fine" must not look the same — and because Terraform can genuinely
 * pass while every credential is absent.
 */
export const CHECKS: DoctorCheck[] = [
  dopplerCheck,
  githubCheck,
  supabaseCheck,
  ...zitadelChecks,
  vercelCheck,
  flyCheck,
  cloudflareCheck,
  terraformCheck,
  terraformStateCheck,
]

export interface RunOptions {
  env?: NodeJS.ProcessEnv
  fetchImpl?: FetchLike
  exec?: CommandExecutor
  repoRoot?: string
  checks?: DoctorCheck[]
}

/**
 * Runs every check and returns the rows. Checks run concurrently — they are
 * independent reads against different providers, and a serial run would make a
 * healthy estate wait on the slowest one.
 */
export async function runChecks(options: RunOptions = {}): Promise<ReportRow[]> {
  const env = options.env ?? process.env
  const ctx: DoctorContext = {
    // Uppercase Doppler aliases are collapsed once, here, so no check has to
    // know that TF_VAR_GITHUB_ORG and TF_VAR_github_org are the same input.
    env: resolveEnv(env),
    fetchImpl: options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike),
    exec: options.exec ?? defaultExecutor,
    repoRoot: options.repoRoot ?? REPO_ROOT,
  }

  const checks = options.checks ?? CHECKS

  return Promise.all(
    checks.map(async (check): Promise<ReportRow> => {
      try {
        return { label: check.label, result: await check.run(ctx) }
      } catch (err) {
        // An unexpected throw is a failure, not a crash: one broken provider
        // must not cost the operator the other eleven answers.
        return { label: check.label, result: { passed: false, error: redact(err, ctx.env) } }
      }
    }),
  )
}

export interface DoctorOutcome {
  rows: ReportRow[]
  output: string
  code: 0 | 1
}

export async function doctor(options: RunOptions = {}): Promise<DoctorOutcome> {
  const rows = await runChecks(options)
  return {
    rows,
    output: formatReport(rows, options.env ?? process.env),
    code: exitCode(rows),
  }
}

/**
 * Captures stdout and stderr; never inherits, so no tool can print a secret
 * past the redactor.
 *
 * No shell: `terraform` is a native executable on every platform, and passing
 * arguments through a shell would leave them unescaped.
 */
const defaultExecutor: CommandExecutor = (command, args, { cwd, env }) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env })
    let stdout = ''
    let stderr = ''
    child.stdout?.on('data', (chunk: Buffer) => (stdout += chunk.toString()))
    child.stderr?.on('data', (chunk: Buffer) => (stderr += chunk.toString()))
    child.on('error', reject)
    child.on('close', (code) => resolve({ exitCode: code ?? 1, stdout, stderr }))
  })
