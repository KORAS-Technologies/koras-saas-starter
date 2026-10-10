// The local ZITADEL masterkey: generated on this machine, cached owner-only,
// escrowed twice, and never written anywhere a person or a process could read
// it by accident.
//
// ZITADEL encrypts an instance's signing keys and secrets with this key and
// cannot change it afterwards. A lost key is a lost instance; a leaked key is
// an instance readable by anyone holding its database. ADR 0015 records why
// each rule below exists.
//
// Exports are the API the planned `koras local` CLI will import. Nothing here
// exits or prints: errors are StackErrors, and stack.mjs's main() decides what
// a person sees.

import { randomInt as cryptoRandomInt } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { chmodSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, statSync, writeSync } from 'node:fs'
import { userInfo } from 'node:os'
import { dirname } from 'node:path'
import { StackError, fingerprint } from './state.mjs'

export { fingerprint }

/**
 * The fingerprint of the key ZITADEL's own documentation uses -- public, and
 * therefore no key at all. Held as a fingerprint so that the placeholder
 * itself appears in exactly one file in a generated project: the legacy
 * override, which is the one place it may be used.
 */
export const PLACEHOLDER_FINGERPRINT = 'sha256:d67cc271c12ad6f95c1b10db7acaf1e69fa8453ef84c898df920faf5d4364f3e'

export function isPlaceholder(key) {
  return fingerprint(key) === PLACEHOLDER_FINGERPRINT
}
export const KEY_LENGTH = 32
export const KEY_CHARSET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

/** Throws unless `key` is exactly 32 characters from [A-Za-z0-9] and not the placeholder. */
export function assertKeyShape(key) {
  if (typeof key !== 'string' || key.length !== KEY_LENGTH) {
    throw new StackError('KEY_SHAPE', `A ZITADEL masterkey is exactly ${KEY_LENGTH} bytes; this one is ${typeof key === 'string' ? key.length : 'not a string'}.`)
  }
  for (const character of key) {
    if (!KEY_CHARSET.includes(character)) throw new StackError('KEY_SHAPE', 'A generated masterkey uses [A-Za-z0-9] only.')
  }
  if (isPlaceholder(key)) {
    throw new StackError('KEY_PLACEHOLDER', 'This is the public placeholder masterkey.', 'A secure instance never runs on it. See ADR 0015.')
  }
}

/**
 * 32 characters from [A-Za-z0-9] via crypto.randomInt: about 190 bits.
 * `randomInt` is injectable so a test can prove the assertions bite.
 */
export function generateKey(randomInt = cryptoRandomInt) {
  let key = ''
  for (let i = 0; i < KEY_LENGTH; i += 1) key += KEY_CHARSET[randomInt(KEY_CHARSET.length)]
  assertKeyShape(key)
  return key
}

function run(command, args, options = {}) {
  return spawnSync(command, args, { encoding: 'utf8', windowsHide: true, ...options })
}

/** Principals in an `icacls <file>` listing, e.g. ["HOST\\alice:(F)"]. */
export function parseIcacls(output, file) {
  const lines = output.split(/\r?\n/)
  const entries = []
  for (let index = 0; index < lines.length; index += 1) {
    let line = lines[index]
    if (index === 0) {
      if (!line.toLowerCase().startsWith(file.toLowerCase())) return null
      line = line.slice(file.length)
    }
    if (line.trim() === '') break
    entries.push(line.trim())
  }
  return entries
}

/** The account the file must belong to on Windows: the one running this. */
function windowsAccount(env) {
  return env.USERNAME || userInfo().username
}

/**
 * Throws unless the file can be read by its owner and nobody else.
 *
 * POSIX: the file is 0600 and owned by this user, and its directory is 0700.
 * Windows: the ACL lists exactly one principal, this user, with no inherited
 * entry -- which is what `icacls /inheritance:r /grant:r <user>:F` leaves.
 */
export function verifySecretFile(path, { platform = process.platform, env = process.env, exec = run } = {}) {
  if (!existsSync(path)) throw new StackError('SECRET_MISSING', `${path} does not exist.`)
  if (platform === 'win32') {
    const listing = exec('icacls', [path])
    if (listing.status !== 0) throw new StackError('SECRET_ACL', `Could not read the ACL of ${path}.`)
    const entries = parseIcacls(listing.stdout ?? '', path)
    if (entries === null) throw new StackError('SECRET_ACL', `Could not parse the ACL of ${path}.`)
    const account = windowsAccount(env).toLowerCase()
    const owner = entries.length === 1 ? entries[0].toLowerCase() : ''
    const principal = owner.split(':(')[0]
    if (entries.length !== 1 || !(principal === account || principal.endsWith('\\' + account)) || owner.includes('(i)')) {
      throw new StackError('SECRET_ACL', `${path} is readable by more than its owner (${entries.length} ACL entries).`, `Expected exactly one: ${windowsAccount(env)}, not inherited.`)
    }
    return
  }
  const file = statSync(path)
  const directory = statSync(dirname(path))
  if ((file.mode & 0o777) !== 0o600) throw new StackError('SECRET_MODE', `${path} has mode ${(file.mode & 0o777).toString(8)}, expected 600.`)
  if ((directory.mode & 0o777) !== 0o700) throw new StackError('SECRET_MODE', `${dirname(path)} has mode ${(directory.mode & 0o777).toString(8)}, expected 700.`)
  if (typeof process.getuid === 'function' && file.uid !== process.getuid()) {
    throw new StackError('SECRET_MODE', `${path} is not owned by the user running this.`)
  }
}

/**
 * Create a secret file that did not exist, owner-only, and verify it.
 *
 * O_CREAT|O_EXCL ('wx'): an existing file is an error, never overwritten. A
 * second provision cannot replace a key an instance was created with.
 */
export function writeSecretFile(path, value, { platform = process.platform, env = process.env, exec = run } = {}) {
  const directory = dirname(path)
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  if (platform !== 'win32') chmodSync(directory, 0o700)
  let descriptor
  try {
    descriptor = openSync(path, 'wx', 0o600)
  } catch (error) {
    if (error.code === 'EEXIST') {
      throw new StackError('SECRET_EXISTS', `${path} already exists and is never overwritten.`, 'An earlier provision left it. `stack.mjs status` says which instance it belongs to.')
    }
    throw error
  }
  try {
    // No trailing newline. ZITADEL v4.17.1 reads --masterkeyFile with
    // os.ReadFile and uses every byte: a newline makes a 33-byte key.
    writeSync(descriptor, value)
  } finally {
    closeSync(descriptor)
  }
  if (platform === 'win32') {
    const granted = exec('icacls', [path, '/inheritance:r', '/grant:r', `${windowsAccount(env)}:F`])
    if (granted.status !== 0) throw new StackError('SECRET_ACL', `Could not restrict the ACL of ${path}.`)
  } else {
    chmodSync(path, 0o600)
  }
  verifySecretFile(path, { platform, env, exec })
}

/** Read a cached secret after verifying who can read it. Never falls back. */
export function readSecretFile(path, options = {}) {
  if (!existsSync(path)) {
    throw new StackError('SECRET_MISSING', `${path} does not exist.`, 'Nothing falls back to a default. Recover it explicitly: `node local/scripts/stack.mjs recover`.')
  }
  verifySecretFile(path, options)
  return readFileSync(path, 'utf8')
}

/**
 * The cached masterkey, or a refusal. Checks, in order: the file exists,
 * only its owner can read it, it is exactly 32 bytes, it is not the
 * placeholder, and its fingerprint is the one the state recorded.
 */
export function readKey(path, { expectedFingerprint, ...options } = {}) {
  if (!existsSync(path)) {
    throw new StackError('KEY_MISSING', `The masterkey cache ${path} is missing.`, 'Nothing falls back to a default key. Recover it explicitly: `node local/scripts/stack.mjs recover` (from Doppler) or `recover --from-backup <artifact>`.')
  }
  verifySecretFile(path, options)
  const size = statSync(path).size
  if (size !== KEY_LENGTH) {
    throw new StackError('KEY_SHAPE', `The masterkey cache ${path} is ${size} bytes, not ${KEY_LENGTH}.`, 'A trailing newline is enough to break it. It was not changed.')
  }
  const key = readFileSync(path, 'utf8')
  if (isPlaceholder(key)) throw new StackError('KEY_PLACEHOLDER', 'The masterkey cache holds the public placeholder.', 'A secure instance never runs on it.')
  assertKeyShape(key)
  if (expectedFingerprint !== undefined && fingerprint(key) !== expectedFingerprint) {
    throw new StackError('KEY_FINGERPRINT', 'The cached masterkey is not the one this instance was created with.', `State records ${expectedFingerprint}; the cache holds ${fingerprint(key)}. Nothing was started.`)
  }
  return key
}
