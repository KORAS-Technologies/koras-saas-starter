// Per-instance admin credentials and expiring access tokens (A14, ADR 0017).
//
// Every new local instance gets its own generated admin password, delivered to
// ZITADEL only through the init steps file, and two personal access tokens --
// the IAM_OWNER machine user's and the login client's -- that expire a year
// after provisioning. Nothing here ever produces ZITADEL's built-in default
// password, which any instance not told otherwise is created with.

import { randomInt as cryptoRandomInt } from 'node:crypto'
import { closeSync, existsSync, fsyncSync, openSync, statSync, unlinkSync, writeSync } from 'node:fs'
import { StackError, fingerprint, writeFileAtomic } from './state.mjs'

/**
 * The fingerprint of ZITADEL's default first-instance password, refused
 * everywhere. A fingerprint rather than the value, so no rendered file
 * carries the default at all.
 */
export const DEFAULT_PASSWORD_FINGERPRINT = 'sha256:1d707811988069ca760826861d6d63a10e8c3b7f171c4441a6472ea58c11711b'

export function isDefaultPassword(password) {
  return fingerprint(password) === DEFAULT_PASSWORD_FINGERPRINT
}
export const PASSWORD_LENGTH = 24
export const UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
export const LOWER = 'abcdefghijklmnopqrstuvwxyz'
export const DIGITS = '0123456789'
// No $, #, quotes, backslash or backtick: compose, YAML and shells each
// reinterpret one of those. What is left still satisfies the policy.
export const SYMBOLS = '!%*+-.:=?@^_~'
export const PAT_LIFETIME_DAYS = 365
export const PAT_WARNING_DAYS = 30

/** ZITADEL's default complexity policy: 8+ characters, upper, lower, digit, symbol. */
export function satisfiesPolicy(password) {
  return (
    typeof password === 'string' &&
    password.length >= 8 &&
    [...password].some((c) => UPPER.includes(c)) &&
    [...password].some((c) => LOWER.includes(c)) &&
    [...password].some((c) => DIGITS.includes(c)) &&
    [...password].some((c) => SYMBOLS.includes(c))
  )
}

/** Throws unless the password is usable for a new instance. */
export function assertPassword(password) {
  if (isDefaultPassword(password)) {
    throw new StackError('DEFAULT_PASSWORD', 'Refusing ZITADEL\'s default admin password.', 'Every new instance gets a generated one. See ADR 0017.')
  }
  const allowed = UPPER + LOWER + DIGITS + SYMBOLS
  if (!satisfiesPolicy(password) || [...password].some((c) => !allowed.includes(c))) {
    throw new StackError('PASSWORD_POLICY', 'The admin password does not meet the complexity policy or uses a disallowed symbol.')
  }
}

/**
 * 24 characters with at least one of each class, shuffled with
 * crypto.randomInt so the guaranteed characters do not sit at fixed positions.
 */
export function generatePassword(randomInt = cryptoRandomInt) {
  const all = UPPER + LOWER + DIGITS + SYMBOLS
  const pick = (set) => set[randomInt(set.length)]
  const characters = [pick(UPPER), pick(LOWER), pick(DIGITS), pick(SYMBOLS)]
  while (characters.length < PASSWORD_LENGTH) characters.push(pick(all))
  for (let i = characters.length - 1; i > 0; i -= 1) {
    const j = randomInt(i + 1)
    ;[characters[i], characters[j]] = [characters[j], characters[i]]
  }
  const password = characters.join('')
  assertPassword(password)
  return password
}

/**
 * Provision time plus 365 days, in ZITADEL's `2006-01-02T15:04:05Z` form.
 * Never empty -- an empty ExpirationDate means a token that never expires.
 */
export function patExpiry(now, days = PAT_LIFETIME_DAYS) {
  const at = new Date(now.getTime() + days * 86_400_000)
  return at.toISOString().replace(/\.\d{3}Z$/, 'Z')
}

/**
 * The init steps file: the one place the admin password reaches ZITADEL.
 *
 * Mounted as a compose secret for `start-from-init` and deleted afterwards, so
 * the password is never in the container's environment and `docker inspect`
 * cannot show it. Single-quoted YAML, which needs no escaping for any
 * character the generator can produce.
 */
export function renderInitSteps({ adminPassword }) {
  assertPassword(adminPassword)
  return [
    '# Rendered by local/scripts/stack.mjs for one start-from-init, then deleted.',
    'FirstInstance:',
    '  Org:',
    '    Human:',
    `      Password: '${adminPassword}'`,
    '      PasswordChangeRequired: false',
    '',
  ].join('\n')
}

/**
 * Overwrite a file with zeros, flush, then unlink. Best effort on SSDs and
 * copy-on-write filesystems, where the old blocks may survive; the cached
 * password in ~/.koras/secrets is the copy that is meant to remain.
 */
export function secureDelete(path) {
  if (!existsSync(path)) return
  const size = statSync(path).size
  const descriptor = openSync(path, 'r+')
  try {
    writeSync(descriptor, Buffer.alloc(size, 0), 0, size, 0)
    fsyncSync(descriptor)
  } finally {
    closeSync(descriptor)
  }
  unlinkSync(path)
}

/** Days until an ISO date, negative once it has passed. */
export function daysUntil(iso, now) {
  return (new Date(iso).getTime() - now.getTime()) / 86_400_000
}

/** Warnings and the one refusal A14 asks for, as data. */
export function patHealth(pats, now) {
  const warnings = []
  let expired = null
  for (const [which, pat] of Object.entries(pats)) {
    if (!pat || !pat.expiresAt) continue
    const days = daysUntil(pat.expiresAt, now)
    if (days <= 0) {
      if (which === 'machine') expired = which
      else warnings.push(`the ${which} access token expired on ${pat.expiresAt}; run \`node local/scripts/stack.mjs rotate-pat ${which === 'loginClient' ? 'login-client' : which}\``)
    } else if (days < PAT_WARNING_DAYS) {
      warnings.push(`the ${which} access token expires in ${Math.ceil(days)} day(s), on ${pat.expiresAt}; run \`node local/scripts/stack.mjs rotate-pat\``)
    }
  }
  return { warnings, expired }
}

/**
 * Replace one access token without ever leaving the instance without a
 * working one. The order is the design:
 *
 *   1. create a new token for the same user, expiring in a year;
 *   2. write it atomically where its consumer reads it;
 *   3. verify the new token works (and, for the login client, restart it);
 *   4. only then delete the old token by id;
 *   5. record the new id and expiry (the caller does, from the return value).
 *
 * A failure at any step before 4 leaves the old token valid and its file in
 * place, because the file is replaced by rename only after the new token
 * exists, and restored if verification fails.
 *
 * `adminToken` is an IAM_OWNER token that creates the new one. `api` is
 * `(method, path, body, token) => Promise<{status, json}>`; every
 * other effect is injected too, so the order is testable without a ZITADEL.
 */
export async function rotatePat({ which, userId, oldTokenId, adminToken, deleteWithNewToken = false, tokenFile, readTokenFile, writeToken, api, now, restartConsumer = async () => {}, verifyConsumer = async () => {} }) {
  if (!oldTokenId) {
    throw new StackError('PAT_UNKNOWN', `No token id is recorded for the ${which} access token.`, 'Rotation deletes the old token by id and will not guess which one that is.')
  }
  const expirationDate = patExpiry(now)
  const created = await api('POST', `/management/v1/users/${userId}/pats`, { expirationDate }, adminToken)
  if (created.status !== 200 || !created.json?.token || !created.json?.tokenId) {
    throw new StackError('PAT_CREATE', `Could not create a new ${which} access token (HTTP ${created.status}). The old one is unchanged.`)
  }
  const previous = readTokenFile(tokenFile)
  writeToken(tokenFile, created.json.token)
  try {
    const check = await api('GET', '/auth/v1/users/me', null, created.json.token)
    if (check.status !== 200 || check.json?.user?.id !== userId) {
      throw new StackError('PAT_VERIFY', `The new ${which} access token did not authenticate as its user (HTTP ${check.status}).`)
    }
    await restartConsumer()
    await verifyConsumer()
  } catch (error) {
    // Put the old token back. The new one is left to expire unused rather
    // than deleted with credentials that have just failed to verify.
    writeToken(tokenFile, previous)
    await restartConsumer().catch(() => {})
    throw error instanceof StackError ? error : new StackError('PAT_VERIFY', `Verifying the new ${which} access token failed: ${error.message}. The old token is back in place.`)
  }
  // The machine user deletes its own old token with its new one; the login
  // client holds IAM_LOGIN_CLIENT only, so its old token is deleted with the
  // machine user's.
  const removed = await api('DELETE', `/management/v1/users/${userId}/pats/${oldTokenId}`, null, deleteWithNewToken ? created.json.token : adminToken)
  // The new token is in use either way, so the caller records it even when
  // the old one survives; a leftover is reported, not thrown.
  const leftover = removed.status === 200 ? null : oldTokenId
  return { tokenId: created.json.tokenId, expiresAt: expirationDate, leftover }
}

/** Atomic, owner-only write of a token file. */
export function writeTokenFile(path, token) {
  writeFileAtomic(path, token, 0o600)
}
