import { spawn } from 'node:child_process'
import type { ProfileDefaults } from '../profiles/types.js'

/**
 * Set on the child so a failed injection cannot loop forever. If Doppler runs
 * but supplies nothing — wrong config, expired token, no access — the child
 * reaches the same "inputs are missing" state that triggered the re-exec, and
 * without this it would wrap itself again.
 */
const REEXEC_FLAG = 'KORAS_DOPPLER_REEXEC'

export interface DopplerLocation {
  project: string
  config: string
}

/**
 * Where the provisioning credentials live.
 *
 * Environment first so a one-off run can point somewhere else without editing
 * a profile; the profile default is the estate-wide answer.
 */
export function resolveDopplerLocation(
  defaults: Pick<ProfileDefaults, 'infrastructure'>,
  env: NodeJS.ProcessEnv = process.env,
): DopplerLocation | undefined {
  const project = env.DOPPLER_PROJECT ?? defaults.infrastructure?.doppler_project
  const config = env.DOPPLER_CONFIG ?? defaults.infrastructure?.doppler_config
  return project && config ? { project, config } : undefined
}

/**
 * Whether this invocation should re-run itself under `doppler run`.
 *
 * `required` is the caller's own question — provisioning needs credentials,
 * plain generation does not — and `satisfied` is whether they are already in
 * the environment, which covers both an operator who exported them by hand and
 * the child of a previous re-exec.
 */
export function shouldReexecUnderDoppler(
  opts: { required: boolean; satisfied: boolean },
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  if (!opts.required) return false
  if (env[REEXEC_FLAG] === '1') return false
  return !opts.satisfied
}

export type Spawner = (
  command: string,
  args: string[],
  env: NodeJS.ProcessEnv,
) => Promise<number>

const defaultSpawner: Spawner = (command, args, env) =>
  new Promise((resolve, reject) => {
    // `doppler` is a real executable on every platform, so no shell is needed
    // and the arguments — a project, a config, and this process's own argv —
    // reach it verbatim.
    const child = spawn(command, args, { stdio: 'inherit', env, shell: false })
    child.on('error', reject)
    child.on('close', (code) => resolve(code ?? 1))
  })

/**
 * Re-runs this CLI under `doppler run`, returning the child's exit code.
 *
 * The whole process is wrapped rather than each Terraform call: every later
 * step — the execution-mode probe, `terraform`, `git`, `pnpm` — then sees the
 * injected environment without needing to know Doppler exists.
 *
 * `--project` and `--config` are always explicit. Generated repositories carry
 * no Doppler scope, so a bare `doppler run` there fails with "You must specify
 * a project".
 */
export async function reexecUnderDoppler(
  location: DopplerLocation,
  argv: string[] = process.argv,
  spawner: Spawner = defaultSpawner,
  env: NodeJS.ProcessEnv = process.env,
): Promise<number> {
  console.log(
    `\nProvisioning credentials are not in this environment — ` +
      `re-running under doppler run (${location.project}/${location.config}).`,
  )

  const [nodeBinary, ...rest] = argv
  return spawner(
    'doppler',
    ['run', '--project', location.project, '--config', location.config, '--', nodeBinary, ...rest],
    { ...env, [REEXEC_FLAG]: '1' },
  )
}

/** Guidance for the case where Doppler is the missing piece, not the secrets. */
export function dopplerUnavailableMessage(location: DopplerLocation): string {
  return [
    '',
    'Could not run `doppler`. Install the Doppler CLI and authenticate, or supply',
    'the inputs another way:',
    '',
    `  doppler run --project ${location.project} --config ${location.config} -- <command>`,
    '',
  ].join('\n')
}
