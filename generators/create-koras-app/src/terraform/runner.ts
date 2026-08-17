import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { GenerationContext } from '../generation/context.js'
import { confirmApply, type ApprovalOptions } from './approval.js'
import {
  formatMissingInputs,
  preflightInputs,
  terraformDirectory,
  generatorProvidedInputs,
  readProjectTfvars,
} from './inputs.js'
import { formatOutputs, parseTerraformOutputs, type ProvisionOutputs } from './outputs.js'

export interface CommandResult {
  exitCode: number
  stdout: string
}

/** Injected so tests never shell out to a real Terraform binary. */
export type CommandExecutor = (
  command: string,
  args: string[],
  options: { cwd: string; capture: boolean },
) => Promise<CommandResult>

export interface ProvisionOptions {
  /** Stop after `plan`; never apply. */
  dryRun: boolean
  projectRoot: string
  exec?: CommandExecutor
  env?: NodeJS.ProcessEnv
  approval?: ApprovalOptions
  /** Force the Doppler wrapper on or off; auto-detected when omitted. */
  useDoppler?: boolean
}

export type ProvisionStatus =
  | 'missing-inputs'
  | 'profile-mismatch'
  | 'init-failed'
  | 'plan-failed'
  | 'planned' // dry run — stopped before apply, as intended
  | 'declined' // human said no
  | 'apply-failed'
  | 'applied'

export interface ProvisionResult {
  status: ProvisionStatus
  outputs?: ProvisionOutputs
}

const PLAN_FILE = 'tfplan'

/**
 * Detects whether Terraform should run under `doppler run`.
 *
 * Doppler is the intended credential source, but the generator must also work
 * from a shell where the variables were exported by other means — so this is a
 * preference, not a requirement.
 */
export function shouldUseDoppler(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.DOPPLER_PROJECT && env.DOPPLER_CONFIG)
}

function wrap(useDoppler: boolean, args: string[]): { command: string; args: string[] } {
  return useDoppler
    ? { command: 'doppler', args: ['run', '--', 'terraform', ...args] }
    : { command: 'terraform', args }
}

export async function provision(
  ctx: GenerationContext,
  options: ProvisionOptions,
): Promise<ProvisionResult> {
  const env = options.env ?? process.env
  const exec = options.exec ?? defaultExecutor
  const cwd = terraformDirectory(options.projectRoot)
  const useDoppler = options.useDoppler ?? shouldUseDoppler(env)

  if (!existsSync(cwd)) {
    throw new Error(
      `No Terraform configuration at ${cwd}.\n` +
        '  The project must be generated before it can be provisioned.',
    )
  }

  // ── Preflight ──────────────────────────────────────────────────────────────
  // Fail before `init` downloads providers, and report every missing input at
  // once rather than one per Terraform run.

  const preflight = preflightInputs(env)
  if (!preflight.ok) {
    console.error('')
    console.error(formatMissingInputs(preflight.missing))
    return { status: 'missing-inputs' }
  }

  // Terraform reads terraform.tfvars itself. Prefer reporting what that file
  // actually says over what today's defaults would produce — with
  // --provision-only the project on disk may predate the current manifest.
  const inputs = generatorProvidedInputs(ctx)
  const tfvarsPath = join(cwd, 'terraform.tfvars')
  const onDisk = existsSync(tfvarsPath)
    ? readProjectTfvars(readFileSync(tfvarsPath, 'utf8'))
    : undefined

  console.log('')
  console.log('Terraform inputs:')
  console.log(`  profile          ${onDisk?.profile ?? inputs.profile}`)
  console.log(`  project_slug     ${onDisk?.projectSlug ?? inputs.project_slug}`)
  console.log(`  enabled_apps     ${JSON.stringify(onDisk?.enabledApps ?? inputs.enabled_apps)}`)
  console.log(
    `  enabled_services ${JSON.stringify(onDisk?.enabledServices ?? inputs.enabled_services)}`,
  )

  if (onDisk?.profile && onDisk.profile !== ctx.profile) {
    console.error('')
    console.error(
      `Refusing to provision: the project on disk was generated with profile ` +
        `"${onDisk.profile}", but "${ctx.profile}" was requested.`,
    )
    return { status: 'profile-mismatch' }
  }
  console.log(
    useDoppler
      ? `\nRunning Terraform under doppler run (${env.DOPPLER_PROJECT}/${env.DOPPLER_CONFIG}).`
      : '\nRunning Terraform with credentials from the current environment.',
  )

  const run = async (args: string[], capture = false) => {
    const { command, args: full } = wrap(useDoppler, args)
    return exec(command, full, { cwd, capture })
  }

  // ── init ───────────────────────────────────────────────────────────────────

  console.log('\n==> terraform init')
  const init = await run(['init', '-input=false'])
  if (init.exitCode !== 0) return { status: 'init-failed' }

  // ── plan ───────────────────────────────────────────────────────────────────

  console.log('\n==> terraform plan')
  const plan = await run(['plan', '-input=false', `-out=${PLAN_FILE}`], true)
  if (plan.exitCode !== 0) return { status: 'plan-failed' }
  if (plan.stdout) console.log(plan.stdout)

  if (options.dryRun) {
    console.log('')
    console.log('--dry-run: stopping after plan. No infrastructure was created.')
    console.log(`Plan saved to ${join(cwd, PLAN_FILE)}.`)
    return { status: 'planned' }
  }

  // ── explicit human approval ────────────────────────────────────────────────

  const approved = await confirmApply(
    {
      projectName: ctx.projectName,
      projectSlug: ctx.projectSlug,
      profile: ctx.profile,
      planSummary: summarisePlan(plan.stdout),
    },
    options.approval ?? {},
  )
  if (!approved) return { status: 'declined' }

  // ── apply ──────────────────────────────────────────────────────────────────
  // The saved plan is applied, so what was approved is exactly what runs.

  console.log('\n==> terraform apply')
  const apply = await run(['apply', '-input=false', PLAN_FILE])
  if (apply.exitCode !== 0) return { status: 'apply-failed' }

  // ── outputs ────────────────────────────────────────────────────────────────

  const output = await run(['output', '-json'], true)
  if (output.exitCode !== 0) {
    console.error('Apply succeeded but outputs could not be read.')
    return { status: 'applied' }
  }

  const outputs = parseTerraformOutputs(output.stdout)
  console.log(formatOutputs(outputs))

  return { status: 'applied', outputs }
}

/** Pulls Terraform's "Plan: N to add, ..." line out of the plan output. */
export function summarisePlan(stdout: string): string | undefined {
  const match = /^Plan: .*$/m.exec(stdout)
  return match?.[0]
}

const defaultExecutor: CommandExecutor = (command, args, { cwd, capture }) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      // Terraform output goes straight to the operator unless we need to parse
      // it. No shell: arguments reach the binary verbatim, so nothing in a
      // project name or path can be interpreted as a shell metacharacter.
      stdio: capture ? ['inherit', 'pipe', 'inherit'] : 'inherit',
      shell: false,
    })

    let stdout = ''
    child.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString()
    })

    child.on('error', (err) => {
      reject(
        new Error(
          `Could not run \`${command}\`: ${err.message}\n` +
            `  Ensure ${command} is installed and on PATH.`,
        ),
      )
    })

    child.on('close', (code) => resolve({ exitCode: code ?? 1, stdout }))
  })
