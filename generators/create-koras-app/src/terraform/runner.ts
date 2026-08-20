import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { GenerationContext } from '../generation/context.js'
import { confirmApply, type ApprovalOptions } from './approval.js'
import {
  formatMissingInputs,
  preflightInputs,
  terraformDirectory,
  generatorProvidedInputs,
  readProjectTfvars,
  resolveTerraformEnv,
} from './inputs.js'
import { formatOutputs, parseTerraformOutputs, type ProvisionOutputs } from './outputs.js'
import { checkExecutionMode, readBackendConfig, type FetchLike } from './backend.js'

export interface CommandResult {
  exitCode: number
  stdout: string
  /** Only populated when the call was made with `stream: true`. */
  stderr?: string
}

/** Injected so tests never shell out to a real Terraform binary. */
export type CommandExecutor = (
  command: string,
  args: string[],
  options: {
    cwd: string
    capture: boolean
    env: NodeJS.ProcessEnv
    /**
     * Echo output to the operator *while* it is captured, rather than holding
     * it until the command exits. Long steps must set this: a silent terminal
     * reads as a hung process, and killing a `terraform plan` mid-flight
     * strands the state lock on the remote backend.
     */
    stream?: boolean
  },
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
  /** Injected for tests; defaults to global fetch. */
  fetchImpl?: FetchLike
}

export type ProvisionStatus =
  | 'missing-inputs'
  | 'profile-mismatch'
  | 'remote-execution'
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

/**
 * Where the saved plan is written.
 *
 * Outside the generated project, deliberately. A Terraform plan embeds a full
 * state snapshot -- every credential Terraform touched, including database
 * passwords and OIDC client secrets it generated -- and the very next thing
 * this CLI does after provisioning is `git add .` and push (see git.ts).
 *
 * Writing it into the project therefore published the estate's credentials to
 * GitHub on every `--provision` run, and did so silently: gitleaks decides
 * whether to look inside an archive from the file extension, and a plan file
 * has none. Measured on a real one: `tfplan` scans as zero bytes and reports
 * nothing, while the byte-identical file named `tfplan.zip` yields 28 findings.
 *
 * A temporary directory removes the artifact rather than hiding it. The
 * .gitignore rule and the git guard are second and third lines, for the plan
 * file nobody has thought of yet.
 */
function createPlanPath(): { path: string; cleanup: () => void } {
  const directory = mkdtempSync(join(tmpdir(), 'koras-plan-'))
  return {
    path: join(directory, 'tfplan'),
    cleanup: () => rmSync(directory, { recursive: true, force: true }),
  }
}

/**
 * Whether a Doppler project and config are configured for this shell.
 *
 * Note that `doppler run` injects DOPPLER_PROJECT and DOPPLER_CONFIG into the
 * child environment, so this is also true when the generator is *already*
 * running under Doppler — see `provision` for why that matters.
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

  if (!existsSync(cwd)) {
    throw new Error(
      `No Terraform configuration at ${cwd}.\n` +
        '  The project must be generated before it can be provisioned.',
    )
  }

  // ── Preflight ──────────────────────────────────────────────────────────────
  // Fail before `init` downloads providers, and report every missing input at
  // once rather than one per Terraform run.

  // Wrapping Terraform in `doppler run` only helps when the inputs are NOT
  // already in this environment. If they are — the usual case, because the
  // generator itself was invoked under `doppler run` — wrapping would nest a
  // second injection for no benefit.
  const preflight = preflightInputs(env)
  const dopplerConfigured = options.useDoppler ?? shouldUseDoppler(env)
  const useDoppler = options.useDoppler ?? (dopplerConfigured && !preflight.ok)

  if (!preflight.ok && !useDoppler) {
    console.error('')
    console.error(formatMissingInputs(preflight.missing, env))
    return { status: 'missing-inputs' }
  }

  if (!preflight.ok && useDoppler) {
    // Doppler can still supply them to the child process even though this
    // process cannot see them.
    console.log('')
    console.log(
      `${preflight.missing.length} input(s) not in this environment; ` +
        'relying on doppler run to supply them:',
    )
    for (const m of preflight.missing) console.log(`  ${m.name}`)
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

  // Terraform reads TF_VAR_/TF_TOKEN_ names case-sensitively, but Doppler can
  // only store uppercase. resolveTerraformEnv maps the aliases across.
  const terraformEnv = resolveTerraformEnv(env)

  const run = async (args: string[], capture = false, stream = false) => {
    const { command, args: full } = wrap(useDoppler, args)
    return exec(command, full, { cwd, capture, env: terraformEnv, stream })
  }

  // ── init ───────────────────────────────────────────────────────────────────

  console.log('\n==> terraform init')
  const init = await run(['init', '-input=false'])
  if (init.exitCode !== 0) return { status: 'init-failed' }

  // ── execution mode ─────────────────────────────────────────────────────────
  // Checked after init, because init is what creates the workspace.

  const backendPath = join(cwd, 'backend.tf')
  const backend = existsSync(backendPath)
    ? readBackendConfig(readFileSync(backendPath, 'utf8'))
    : undefined

  if (backend) {
    const mode = await checkExecutionMode(
      backend,
      terraformEnv.TF_TOKEN_app_terraform_io,
      options.fetchImpl,
    )
    if (mode.status === 'remote') {
      console.error('')
      console.error(mode.message)
      return { status: 'remote-execution' }
    }
    if (mode.status === 'unknown') {
      console.log(`\nCould not confirm execution mode (${mode.reason}); continuing.`)
    }
  }

  // ── plan ───────────────────────────────────────────────────────────────────

  console.log('\n==> terraform plan')
  const planFile = createPlanPath()
  // Streamed, not buffered. A plan across this estate contacts eight providers
  // and can run for minutes; withholding its output until exit makes it look
  // hung, and a plan killed mid-flight leaves the remote backend locked.
  const plan = await run(['plan', '-input=false', `-out=${planFile.path}`], true, true)
  if (plan.exitCode !== 0) {
    planFile.cleanup()
    const recovery = stateLockRecovery(plan.stderr, useDoppler)
    if (recovery) console.error(recovery)
    return { status: 'plan-failed' }
  }

  if (options.dryRun) {
    console.log('')
    console.log('--dry-run: stopping after plan. No infrastructure was created.')
    // The path is reported rather than the plan kept somewhere convenient: it
    // holds credentials, and a convenient location is one someone commits.
    console.log(`Plan saved to ${planFile.path} (outside the project; delete when done).`)
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
  if (!approved) {
    planFile.cleanup()
    return { status: 'declined' }
  }

  // ── apply ──────────────────────────────────────────────────────────────────
  // The saved plan is applied, so what was approved is exactly what runs.

  console.log('\n==> terraform apply')
  const apply = await run(['apply', '-input=false', planFile.path])
  // Removed whether or not the apply succeeded. A failed apply leaves a plan
  // that is just as full of credentials as a successful one.
  planFile.cleanup()
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

/**
 * Turns a state-lock failure into the exact command that clears it.
 *
 * The lock ID that `force-unlock` wants is the one Terraform names as the
 * *lock ID* — for the `remote` backend that is `<org>/<workspace>`, not the
 * UUID printed under `Lock Info:`. Passing the UUID is rejected with
 * "does not match existing lock ID", which is a confusing place to land while
 * provisioning, so the ID is read straight out of the error rather than
 * reconstructed.
 *
 * Returns undefined when the failure was not a lock failure.
 */
export function stateLockRecovery(stderr = '', useDoppler = false): string | undefined {
  if (!/Error acquiring the state lock/.test(stderr)) return undefined

  const lockId = /lock ID: "([^"]+)"/.exec(stderr)?.[1]
  if (!lockId) return undefined

  const prefix = useDoppler ? 'doppler run -- ' : ''
  return [
    '',
    'The workspace is locked. If no other plan or apply is running — check for a',
    'live terraform process, and for a queued run in the workspace — release it:',
    '',
    `  ${prefix}terraform force-unlock ${lockId}`,
    '',
    'Run it from the project’s infrastructure/terraform directory, then retry.',
  ].join('\n')
}

/** Pulls Terraform's "Plan: N to add, ..." line out of the plan output. */
export function summarisePlan(stdout: string): string | undefined {
  const match = /^Plan: .*$/m.exec(stdout)
  return match?.[0]
}

const defaultExecutor: CommandExecutor = (command, args, { cwd, capture, env, stream }) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env,
      // Terraform output goes straight to the operator unless we need to parse
      // it. `stream` needs both pipes: stdout so progress can be echoed as it
      // arrives, stderr so a lock failure can be turned into a recovery hint.
      // No shell: arguments reach the binary verbatim, so nothing in a project
      // name or path can be interpreted as a shell metacharacter.
      stdio: stream
        ? ['inherit', 'pipe', 'pipe']
        : capture
          ? ['inherit', 'pipe', 'inherit']
          : 'inherit',
      shell: false,
    })

    let stdout = ''
    let stderr = ''
    child.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString()
      if (stream) process.stdout.write(chunk)
    })
    child.stderr?.on('data', (chunk: Buffer) => {
      stderr += chunk.toString()
      if (stream) process.stderr.write(chunk)
    })

    child.on('error', (err) => {
      reject(
        new Error(
          `Could not run \`${command}\`: ${err.message}\n` +
            `  Ensure ${command} is installed and on PATH.`,
        ),
      )
    })

    child.on('close', (code) => resolve({ exitCode: code ?? 1, stdout, stderr }))
  })
