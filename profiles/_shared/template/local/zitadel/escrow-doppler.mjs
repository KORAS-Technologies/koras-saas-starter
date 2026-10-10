// Escrow leg 1: a per-machine Doppler branch config (A2, ADR 0015).
//
// Doppler project <product>, config dev_local_<machineId>, under the `dev`
// environment. Write-once: an absent secret is written and read back; a
// present one is compared and never overwritten. The developer's own `doppler`
// login is used, never a CI service token -- deployment tokens are scoped to
// the deployed configs and must not be able to read these.
//
// Values travel on stdin, never in argv, where any process on the machine
// could read them. Nothing here prints a value.

import { spawnSync } from 'node:child_process'
import { StackError, fingerprint } from './state.mjs'

export const CONFIG_PATTERN = /^dev_local_[a-z0-9][a-z0-9-]*$/

function run(command, args, options = {}) {
  // No shell, on any platform: arguments are passed as a vector, so a project
  // or config name can never be read as shell syntax.
  return spawnSync(command, args, { encoding: 'utf8', windowsHide: true, ...options })
}

export function dopplerConfigName(machineId) {
  const name = `dev_local_${machineId}`
  if (!CONFIG_PATTERN.test(name)) throw new StackError('DOPPLER_CONFIG', `${name} is not a valid per-machine config name.`)
  return name
}

function assertMachineConfig(config) {
  // The guard that keeps escrow out of anything a deployment reads. The `dev`
  // root, `dev_feature`, `stg`, `prd`: all refused here as well as by
  // doppler-check.sh.
  if (!CONFIG_PATTERN.test(config)) {
    throw new StackError('DOPPLER_CONFIG', `Refusing to escrow into Doppler config '${config}'.`, 'Escrow goes only to a per-machine dev_local_<machine> branch config.')
  }
}

/**
 * Whether leg 1 can be written: the CLI answers, and the per-machine config
 * exists under the `dev` environment. Configs are never created here: who may
 * create them is the owner's decision (spec open item 2).
 */
export function checkDoppler({ project, config, exec = run }) {
  assertMachineConfig(config)
  const result = exec('doppler', ['configs', 'get', config, '--project', project, '--json'])
  if (result.error || result.status !== 0) {
    return { ok: false, reason: `Doppler config ${project}/${config} cannot be read (is the CLI logged in, and has the config been created?)` }
  }
  let parsed
  try {
    parsed = JSON.parse(result.stdout)
  } catch {
    return { ok: false, reason: `Doppler answered for ${project}/${config} with something that is not JSON` }
  }
  if (parsed.environment !== 'dev') {
    return { ok: false, reason: `Doppler config ${config} is in environment '${parsed.environment}', not 'dev'` }
  }
  return { ok: true }
}

function names({ project, config, exec }) {
  const listed = exec('doppler', ['secrets', '--only-names', '--json', '--project', project, '--config', config])
  if (listed.error || listed.status !== 0) {
    throw new StackError('DOPPLER_READ', `Could not list the names in ${project}/${config}.`)
  }
  // Write-once depends on this list: a name missing from it is written over.
  // So the two shapes a name listing can take are read explicitly, and any
  // other answer is a refusal rather than an empty list. The real CLI's shape
  // is confirmed by manual case T-E4, not by the fakes.
  let parsed
  try {
    parsed = JSON.parse(listed.stdout)
  } catch {
    throw new StackError('DOPPLER_READ', `Doppler listed the names in ${project}/${config} as something that is not JSON.`)
  }
  if (Array.isArray(parsed) && parsed.every((name) => typeof name === 'string')) return parsed
  if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) return Object.keys(parsed)
  throw new StackError('DOPPLER_READ', `Doppler listed the names in ${project}/${config} in a shape this script does not know, so nothing was written.`)
}

function getValue({ project, config, name, exec }) {
  const got = exec('doppler', ['secrets', 'get', name, '--plain', '--project', project, '--config', config])
  if (got.error || got.status !== 0) throw new StackError('DOPPLER_READ', `Could not read ${name} back from ${project}/${config}.`)
  // `--plain` prints the value and a newline.
  return got.stdout.replace(/\r?\n$/, '')
}

/**
 * Write-once escrow of one secret. Returns 'written' or 'unchanged'.
 *
 *   absent            write it, read it back, compare fingerprints;
 *   present, equal    no-op;
 *   present, differs  refuse. An escrowed key is never overwritten.
 */
export function escrowSecret({ project, config, name, value, exec = run }) {
  assertMachineConfig(config)
  if (names({ project, config, exec }).includes(name)) {
    const existing = getValue({ project, config, name, exec })
    if (fingerprint(existing) === fingerprint(value)) return 'unchanged'
    throw new StackError('ESCROW_CONFLICT', `${project}/${config} already holds a different ${name}.`, 'It was not overwritten, and never will be. ADR 0015 explains what a second instance on one machine needs.')
  }
  const written = exec('doppler', ['secrets', 'set', name, '--project', project, '--config', config, '--silent'], { input: value })
  if (written.error || written.status !== 0) throw new StackError('DOPPLER_WRITE', `Could not write ${name} to ${project}/${config}.`)
  if (fingerprint(getValue({ project, config, name, exec })) !== fingerprint(value)) {
    throw new StackError('DOPPLER_VERIFY', `${name} read back from ${project}/${config} does not match what was written.`)
  }
  return 'written'
}

/** The escrowed value, for an explicit `recover` and nothing else. */
export function recoverSecret({ project, config, name, exec = run }) {
  assertMachineConfig(config)
  if (!names({ project, config, exec }).includes(name)) {
    throw new StackError('ESCROW_ABSENT', `${project}/${config} holds no ${name}.`)
  }
  return getValue({ project, config, name, exec })
}
