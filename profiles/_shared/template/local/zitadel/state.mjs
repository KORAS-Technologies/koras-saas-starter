// The local ZITADEL instance's identity, kept outside the repository.
//
// ~/.koras/state/<product>/zitadel.json is the single record of which instance
// this checkout drives: its mode, its issuer and login ports, the fingerprint
// of its masterkey, where that key is escrowed and when its access tokens
// expire. It lives in the home directory so that a branch switch, a worktree
// or a `git clean -fdx` cannot lose it -- losing it is how an instance ends up
// started with the wrong key or re-initialised over.
//
// Pure functions and small file helpers only. Exit codes and messages belong
// to stack.mjs's main(), which is what the planned `koras local` CLI replaces.

import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync, chmodSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'

export const SCHEMA_VERSION = 2
export const MODES = ['secure', 'legacy-recovery']
export const PHASES = ['provisioning', 'ready']

/** A refusal with a reason a person can act on. stack.mjs turns it into an exit. */
export class StackError extends Error {
  constructor(code, message, hint) {
    super(message)
    this.name = 'StackError'
    this.code = code
    this.hint = hint
  }
}

/**
 * sha256 of a value, as `sha256:<hex>`. An identity for comparison, never a
 * password hash: only for generated high-entropy values (the 190-bit key, the
 * 141-bit-plus admin password) and for refusing public constants. Never use it
 * on a password a person chose. ADR 0017 has the CodeQL disposition this
 * depends on.
 */
export function fingerprint(value) {
  return 'sha256:' + createHash('sha256').update(value, 'utf8').digest('hex')
}

/** ~/.koras, or KORAS_HOME when set (tests, and nothing else, set it). */
export function korasHome(env = process.env) {
  return env.KORAS_HOME ? resolve(env.KORAS_HOME) : join(homedir(), '.koras')
}

/** Every path the stack reads or writes outside the repository, in one place. */
export function paths(product, envName = 'dev', env = process.env) {
  const home = korasHome(env)
  const secretsDir = join(home, 'secrets', product, envName)
  const stateDir = join(home, 'state', product)
  return {
    home,
    secretsDir,
    masterkey: join(secretsDir, 'zitadel-masterkey'),
    adminPassword: join(secretsDir, 'zitadel-admin-password'),
    initSteps: join(secretsDir, 'zitadel-init-steps.yaml'),
    stateDir,
    state: join(stateDir, 'zitadel.json'),
    // An empty file compose may mount when no key is wanted: every command but
    // `up` still has to load the whole compose file, and the key's `:?` guard
    // would refuse them all. ZITADEL refuses a 0-byte key, so mounting this by
    // mistake fails closed rather than starting anything.
    absentKey: join(stateDir, 'zitadel-masterkey.absent'),
    escrowBackupDir: join(home, 'escrow-backup'),
    machine: join(home, 'machine.json'),
    recipient: join(home, 'recovery-recipient.json'),
  }
}

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/
const FINGERPRINT = /^sha256:[0-9a-f]{64}$/

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Every problem with a state object, as a list. Empty means valid.
 *
 * Strict on purpose. A state file is the only thing standing between `up` and
 * starting an instance with the wrong key, so a field that is present but
 * malformed is refused rather than defaulted.
 */
export function validateState(state) {
  const problems = []
  if (!isObject(state)) return ['state is not a JSON object']
  if (state.schemaVersion !== SCHEMA_VERSION) {
    // A v1 file is refused rather than migrated: none exist, and a migration
    // nobody exercised is a guess about somebody's instance.
    problems.push(`schemaVersion is ${JSON.stringify(state.schemaVersion)}, expected ${SCHEMA_VERSION}`)
    return problems
  }
  for (const field of ['product', 'env', 'composeProject', 'database', 'issuer', 'zitadelVersion', 'createdAt']) {
    if (typeof state[field] !== 'string' || state[field] === '') problems.push(`${field} is missing`)
  }
  if (!MODES.includes(state.mode)) problems.push(`mode ${JSON.stringify(state.mode)} is not one of ${MODES.join(', ')}`)
  if (!PHASES.includes(state.phase)) problems.push(`phase ${JSON.stringify(state.phase)} is not one of ${PHASES.join(', ')}`)
  if (state.instanceId !== null && typeof state.instanceId !== 'string') problems.push('instanceId must be a string or null')
  if (typeof state.issuer === 'string' && !/^http:\/\/localhost:\d+$/.test(state.issuer)) {
    problems.push('issuer must be http://localhost:<port>')
  }
  if (!isObject(state.escrow)) problems.push('escrow is missing')
  if (!isObject(state.admin)) problems.push('admin is missing')
  if (!isObject(state.pats)) problems.push('pats is missing')

  if (state.mode === 'secure') {
    if (!FINGERPRINT.test(state.masterkeyFingerprint ?? '')) problems.push('a secure instance needs masterkeyFingerprint')
    if (typeof state.loginBaseUri !== 'string' || !/^http:\/\/localhost:\d+\/ui\/v2\/login\/$/.test(state.loginBaseUri)) {
      problems.push('a secure instance needs loginBaseUri http://localhost:<port>/ui/v2/login/')
    }
    if (isObject(state.escrow)) {
      if (!['escrowed', 'unescrowed'].includes(state.escrow.status)) problems.push('escrow.status must be escrowed or unescrowed')
      for (const leg of ['doppler', 'backup']) {
        if (!isObject(state.escrow[leg]) || !['done', 'pending'].includes(state.escrow[leg].status)) {
          problems.push(`escrow.${leg}.status must be done or pending`)
        }
      }
      // The invariant that matters most: "escrowed" means both legs. A state
      // claiming escrowed with one leg pending is refused, not believed.
      const both = state.escrow.doppler?.status === 'done' && state.escrow.backup?.status === 'done'
      if (state.escrow.status === 'escrowed' && !both) problems.push('escrow.status is escrowed but a leg is pending')
    }
    if (isObject(state.admin) && !FINGERPRINT.test(state.admin.passwordFingerprint ?? '')) {
      problems.push('a secure instance needs admin.passwordFingerprint')
    }
  } else if (state.mode === 'legacy-recovery') {
    if (state.masterkeyFingerprint !== null) problems.push('a legacy instance records no masterkeyFingerprint')
    if (state.loginBaseUri !== null) problems.push('a legacy instance has no loginBaseUri')
    if (isObject(state.escrow) && state.escrow.status !== 'n/a') problems.push('a legacy instance has escrow.status n/a')
    if (typeof state.instanceId !== 'string' || state.instanceId === '') problems.push('a legacy instance is pinned to an instanceId')
  }
  if (isObject(state.pats)) {
    for (const which of ['machine', 'loginClient']) {
      const pat = state.pats[which]
      if (!isObject(pat)) {
        problems.push(`pats.${which} is missing`)
        continue
      }
      if (pat.expiresAt !== null && !ISO.test(pat.expiresAt ?? '')) problems.push(`pats.${which}.expiresAt is not an ISO date`)
    }
  }
  return problems
}

/** The state file, validated, or null when there is none. Never repairs. */
export function readState(path) {
  if (!existsSync(path)) return null
  let parsed
  try {
    parsed = JSON.parse(readFileSync(path, 'utf8'))
  } catch (error) {
    throw new StackError('STATE_UNREADABLE', `The state file ${path} is not valid JSON.`, 'It was not changed. Inspect it by hand; nothing will be inferred from a damaged record.')
  }
  const problems = validateState(parsed)
  if (problems.length > 0) {
    throw new StackError('STATE_INVALID', `The state file ${path} is not valid:\n  - ${problems.join('\n  - ')}`, 'It was not changed. Nothing starts against an instance whose record cannot be trusted.')
  }
  return parsed
}

/**
 * Write a file atomically: a temporary file in the same directory, then a
 * rename. A crash leaves either the old file or the new one, never half of one.
 */
export function writeFileAtomic(path, contents, mode = 0o600) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`
  writeFileSync(temporary, contents, { mode, flag: 'wx' })
  if (process.platform !== 'win32') chmodSync(temporary, mode)
  renameSync(temporary, path)
}

/** Validate, then write atomically. An invalid state is never written. */
export function writeState(path, state) {
  const problems = validateState(state)
  if (problems.length > 0) {
    throw new StackError('STATE_INVALID', `Refusing to write an invalid state:\n  - ${problems.join('\n  - ')}`)
  }
  writeFileAtomic(path, JSON.stringify(state, null, 2) + '\n')
}

/** The skeleton of a new secure instance's record, before it has an instance. */
export function newSecureState({ product, composeProject, issuer, loginBaseUri, masterkeyFingerprint, passwordFingerprint, dopplerConfig, zitadelVersion, now }) {
  return {
    schemaVersion: SCHEMA_VERSION,
    product,
    env: 'dev',
    mode: 'secure',
    composeProject,
    database: 'zitadel',
    instanceId: null,
    issuer,
    loginBaseUri,
    masterkeyFingerprint,
    escrow: {
      status: 'unescrowed',
      doppler: { status: 'pending', config: dopplerConfig, at: null },
      backup: { status: 'pending', recipient: null, sha256: null, paths: [], copies: [], at: null },
    },
    admin: { username: 'admin', passwordFingerprint },
    pats: {
      machine: { tokenId: null, expiresAt: null },
      loginClient: { tokenId: null, expiresAt: null },
    },
    zitadelVersion,
    phase: 'provisioning',
    initCompletedAt: null,
    createdAt: now.toISOString(),
  }
}

/** A legacy instance's record: pinned to an instance, holding no key identity. */
export function newLegacyState({ product, composeProject, issuer, instanceId, zitadelVersion, now }) {
  return {
    schemaVersion: SCHEMA_VERSION,
    product,
    env: 'dev',
    mode: 'legacy-recovery',
    composeProject,
    database: 'zitadel',
    instanceId,
    issuer,
    loginBaseUri: null,
    masterkeyFingerprint: null,
    escrow: { status: 'n/a' },
    admin: { username: 'admin', passwordFingerprint: null },
    pats: {
      machine: { tokenId: null, expiresAt: null },
      loginClient: { tokenId: null, expiresAt: null },
    },
    zitadelVersion,
    phase: 'ready',
    createdAt: now.toISOString(),
  }
}

/** Recompute escrow.status from its legs. The only place it is ever set. */
export function settleEscrow(state) {
  const both = state.escrow.doppler.status === 'done' && state.escrow.backup.status === 'done'
  return { ...state, escrow: { ...state.escrow, status: both ? 'escrowed' : 'unescrowed' } }
}
