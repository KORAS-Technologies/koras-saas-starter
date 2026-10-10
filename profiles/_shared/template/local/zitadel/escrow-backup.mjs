// Escrow leg 2: an encrypted backup recoverable without Doppler and without
// this machine (A2 as amended, ADR 0015).
//
// The key is encrypted with gpg to the owner's OpenPGP recovery key, whose
// private half is held offline and never on a development machine. This
// machine holds only the public key, pinned by full fingerprint in
// ~/.koras/recovery-recipient.json, installed once by the owner:
//
//   { "fingerprint": "<40 or 64 hex>", "armoredPublicKey": "-----BEGIN PGP ..." }
//
// Symmetric encryption is rejected: its passphrase would live on the same
// machine as the backup, so the backup would not be independent of it.
//
// The machine cannot decrypt what it writes, so verification is structural:
// exactly one public-key-encrypted session key packet, addressed to an
// encryption subkey of the pinned key, and a ciphertext digest that matches the
// sidecar. Only a recovery drill on the offline machine (T-E6) proves the
// backup decrypts.
//
// Every gpg call uses a throwaway --homedir, so nothing here reads or changes
// the user's own keyring -- except `decryptArtifact`, which exists for the
// recovery machine and uses the keyring that holds the private key.

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, constants, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { basename, join, parse, sep } from 'node:path'
import { StackError, fingerprint, writeFileAtomic } from './state.mjs'

function run(command, args, options = {}) {
  return spawnSync(command, args, { encoding: 'utf8', windowsHide: true, ...options })
}

export function sha256File(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

/**
 * The path form this gpg understands. Git for Windows ships an MSYS gpg whose
 * home is `/c/Users/...` and which reads `C:\...` as a relative path; Gpg4win
 * wants native paths. Decided once from `gpg --version`'s Home line.
 */
export function gpgPathStyle({ exec = run, platform = process.platform, gpg = 'gpg' } = {}) {
  if (platform !== 'win32') return 'native'
  const version = exec(gpg, ['--version'])
  const home = /^Home:\s*(.*)$/m.exec(version.stdout ?? '')?.[1] ?? ''
  return home.startsWith('/') ? 'msys' : 'native'
}

export function toGpgPath(path, style) {
  if (style !== 'msys') return path
  const forward = path.split(sep).join('/')
  return /^[A-Za-z]:\//.test(forward) ? '/' + forward[0].toLowerCase() + forward.slice(2) : forward
}

function gpgContext(options = {}) {
  const gpg = options.gpg ?? process.env.KORAS_GPG ?? 'gpg'
  const exec = options.exec ?? run
  const style = gpgPathStyle({ exec, platform: options.platform, gpg })
  const home = mkdtempSync(join(tmpdir(), 'koras-gpg-'))
  const call = (args, extra = {}) => exec(gpg, ['--homedir', toGpgPath(home, style), '--batch', '--no-tty', ...args], extra)
  const cleanup = () => {
    exec('gpgconf', ['--homedir', toGpgPath(home, style), '--kill', 'gpg-agent'])
    rmSync(home, { recursive: true, force: true })
  }
  return { call, cleanup, path: (p) => toGpgPath(p, style) }
}

/** Parse `--with-colons` key output into the primary fingerprint and its encryption keys. */
export function parseKeyListing(colons) {
  const keys = []
  let current = null
  let pending = null
  for (const line of colons.split(/\r?\n/)) {
    const fields = line.split(':')
    if (fields[0] === 'pub') {
      current = { primary: null, encryptionKeys: [] }
      keys.push(current)
      pending = { kind: 'pub', canEncrypt: (fields[11] ?? '').includes('e') }
    } else if (fields[0] === 'sub' && current) {
      pending = { kind: 'sub', canEncrypt: (fields[11] ?? '').includes('e') }
    } else if (fields[0] === 'fpr' && current && pending) {
      const fpr = fields[9]
      if (pending.kind === 'pub') current.primary = fpr
      if (pending.canEncrypt) current.encryptionKeys.push(fpr)
      pending = null
    }
  }
  return keys
}

/**
 * Load and pin the recovery recipient. Throws when the file is malformed or
 * its key is not the one pinned; returns null when it is simply not installed,
 * which leaves leg 2 pending rather than failing.
 */
export function loadRecipient(path, options = {}) {
  if (!existsSync(path)) return null
  let parsed
  try {
    parsed = JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    throw new StackError('RECIPIENT_INVALID', `${path} is not valid JSON.`)
  }
  const pinned = String(parsed.fingerprint ?? '').replace(/\s+/g, '').toUpperCase()
  if (!/^([0-9A-F]{40}|[0-9A-F]{64})$/.test(pinned)) {
    throw new StackError('RECIPIENT_INVALID', `${path} must pin a full OpenPGP fingerprint (40 or 64 hex characters).`)
  }
  if (typeof parsed.armoredPublicKey !== 'string' || !parsed.armoredPublicKey.includes('BEGIN PGP PUBLIC KEY BLOCK')) {
    throw new StackError('RECIPIENT_INVALID', `${path} must carry the recovery public key as armoredPublicKey.`)
  }
  const gpg = gpgContext(options)
  try {
    const shown = gpg.call(['--with-colons', '--import-options', 'show-only', '--import'], { input: parsed.armoredPublicKey })
    if (shown.status !== 0) throw new StackError('RECIPIENT_INVALID', `gpg could not read the recovery public key in ${path}.`)
    const keys = parseKeyListing(shown.stdout)
    if (keys.length !== 1) throw new StackError('RECIPIENT_INVALID', `${path} must hold exactly one public key; it holds ${keys.length}.`)
    if (keys[0].primary !== pinned) {
      throw new StackError('RECIPIENT_MISMATCH', `The recovery public key in ${path} is ${keys[0].primary}, not the pinned ${pinned}.`, 'Nothing was encrypted. Ask the owner for the recovery key again.')
    }
    if (keys[0].encryptionKeys.length === 0) throw new StackError('RECIPIENT_INVALID', 'The recovery key has no encryption-capable key.')
    return { fingerprint: pinned, armoredPublicKey: parsed.armoredPublicKey, encryptionKeys: keys[0].encryptionKeys }
  } finally {
    gpg.cleanup()
  }
}

/**
 * Whether the backup directory is on a different volume from the user
 * profile. A copy on the same disk as the cache is lost with it.
 */
export function checkBackupDestination(dir, { home = homedir(), platform = process.platform } = {}) {
  if (!dir) return { ok: false, reason: 'KORAS_ESCROW_BACKUP_DIR is not set' }
  if (!existsSync(dir)) return { ok: false, reason: `KORAS_ESCROW_BACKUP_DIR (${dir}) does not exist` }
  const resolved = realpathSync(dir)
  const sameDevice = statSync(resolved).dev === statSync(home).dev
  const sameDrive = platform === 'win32' && parse(resolved).root.toLowerCase() === parse(realpathSync(home)).root.toLowerCase()
  if (sameDevice || sameDrive) {
    return { ok: false, reason: `KORAS_ESCROW_BACKUP_DIR (${resolved}) is on the same volume as the user profile` }
  }
  return { ok: true, dir: resolved }
}

/** `gpg --list-packets` without any secret key: the key ids it was encrypted to. */
export function packetRecipients(file, options = {}) {
  const gpg = gpgContext(options)
  try {
    // Exits non-zero, because nothing here can decrypt. The listing is still
    // complete; only the packets matter.
    const listed = gpg.call(['--list-packets', gpg.path(file)])
    const ids = [...(listed.stdout ?? '').matchAll(/^:pubkey enc packet:.*keyid ([0-9A-F]{16})/gim)].map((m) => m[1].toUpperCase())
    return ids
  } finally {
    gpg.cleanup()
  }
}

/** Throws unless the artifact is addressed only to the pinned recipient and matches its sidecar. */
export function verifyArtifact({ artifact, sidecar, recipient, ...options }) {
  if (sidecar.recipient !== recipient.fingerprint) {
    throw new StackError('BACKUP_RECIPIENT', `${basename(artifact)} was written for ${sidecar.recipient}, not the pinned ${recipient.fingerprint}.`)
  }
  const digest = sha256File(artifact)
  if (digest !== sidecar.ciphertextSha256) {
    throw new StackError('BACKUP_DIGEST', `${basename(artifact)} does not match the digest in its sidecar.`, 'It was not replaced. Something changed it after it was written.')
  }
  const ids = packetRecipients(artifact, options)
  const allowed = recipient.encryptionKeys.map((fpr) => fpr.slice(-16))
  if (ids.length !== 1 || !allowed.includes(ids[0])) {
    throw new StackError('BACKUP_PACKETS', `${basename(artifact)} has ${ids.length} session-key packet(s) (${ids.join(', ') || 'none'}); expected exactly one, to the pinned recovery key.`)
  }
  return digest
}

export function artifactName({ product, machineId, keyFingerprint }) {
  const fp8 = keyFingerprint.replace(/^sha256:/, '').slice(0, 8)
  return `zitadel-masterkey.${product}.${machineId}.${fp8}.gpg`
}

function readSidecar(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

function encrypt({ plaintext, recipient, output, ...options }) {
  const gpg = gpgContext(options)
  try {
    const imported = gpg.call(['--quiet', '--import'], { input: recipient.armoredPublicKey })
    if (imported.status !== 0) throw new StackError('BACKUP_ENCRYPT', 'gpg could not import the recovery public key.')
    // --trust-model always is safe only because this keyring is throwaway and
    // holds exactly the key whose fingerprint was just pinned.
    const encrypted = gpg.call(['--trust-model', 'always', '--recipient', recipient.fingerprint, '--encrypt', '--output', gpg.path(output)], { input: plaintext })
    if (encrypted.status !== 0) throw new StackError('BACKUP_ENCRYPT', `gpg could not encrypt to the recovery key: ${(encrypted.stderr ?? '').trim().split('\n').pop()}`)
  } finally {
    gpg.cleanup()
  }
}

/** Copy write-once: absent is copied and verified; present must be byte-identical. */
function copyOnce(source, target) {
  if (existsSync(target)) {
    if (sha256File(target) !== sha256File(source)) {
      throw new StackError('BACKUP_CONFLICT', `${target} exists with different contents.`, 'It was not replaced.')
    }
    return
  }
  copyFileSync(source, target, constants.COPYFILE_EXCL)
  if (sha256File(target) !== sha256File(source)) throw new StackError('BACKUP_COPY', `The copy at ${target} does not match its source.`)
}

/**
 * Write leg 2 for one key. Returns the leg's state: `done` with its evidence,
 * or `pending` with the reason. It never reports `done` without having
 * verified the artifact in both places.
 */
export function escrowBackup({ key, keyFingerprint, product, machineId, instanceId = null, recipientPath, backupDir, localDir, now, home = homedir(), platform = process.platform, ...options }) {
  const recipient = loadRecipient(recipientPath, { platform, ...options })
  if (recipient === null) return { status: 'pending', reason: `no recovery recipient at ${recipientPath}` }
  const destination = checkBackupDestination(backupDir, { home, platform })
  if (!destination.ok) return { status: 'pending', reason: destination.reason }
  if (fingerprint(key) !== keyFingerprint) throw new StackError('KEY_FINGERPRINT', 'The key handed to escrow is not the recorded one.')

  mkdirSync(localDir, { recursive: true, mode: 0o700 })
  const name = artifactName({ product, machineId, keyFingerprint })
  const artifact = join(localDir, name)
  const sidecarPath = `${artifact}.json`

  if (existsSync(artifact)) {
    // Write-once. gpg output is not deterministic, so an existing artifact is
    // verified and kept, never re-encrypted over.
    if (!existsSync(sidecarPath)) throw new StackError('BACKUP_CONFLICT', `${artifact} exists without its sidecar.`, 'It was not replaced.')
    const sidecar = readSidecar(sidecarPath)
    if (sidecar.keyFingerprint !== keyFingerprint) throw new StackError('BACKUP_CONFLICT', `${artifact} belongs to a different key.`)
    verifyArtifact({ artifact, sidecar, recipient, platform, ...options })
  } else {
    const staging = `${artifact}.${process.pid}.partial`
    rmSync(staging, { force: true })
    encrypt({ plaintext: key, recipient, output: staging, platform, ...options })
    const sidecar = {
      product,
      machineId,
      instanceId,
      keyFingerprint,
      recipient: recipient.fingerprint,
      ciphertextSha256: sha256File(staging),
      createdAt: now.toISOString(),
      copies: [],
    }
    verifyArtifact({ artifact: staging, sidecar, recipient, platform, ...options })
    copyFileSync(staging, artifact, constants.COPYFILE_EXCL)
    rmSync(staging, { force: true })
    writeFileAtomic(sidecarPath, JSON.stringify(sidecar, null, 2) + '\n', 0o644)
  }

  const sidecar = readSidecar(sidecarPath)
  const external = join(destination.dir, name)
  copyOnce(artifact, external)
  // The sidecar is metadata, not ciphertext: it gains an instance id and
  // recorded copies over time, so it is mirrored rather than written once.
  writeFileAtomic(`${external}.json`, readFileSync(sidecarPath, 'utf8'), 0o644)
  verifyArtifact({ artifact: external, sidecar, recipient, platform, ...options })

  return {
    status: 'done',
    recipient: recipient.fingerprint,
    sha256: sidecar.ciphertextSha256,
    paths: [artifact, external],
    copies: sidecar.copies,
    at: now.toISOString(),
  }
}

/** Record an off-machine copy the owner made, by label. The artifact is untouched. */
export function recordCopy({ sidecarPaths, label, now }) {
  const sidecar = readSidecar(sidecarPaths[0])
  if (!sidecar.copies.some((copy) => copy.label === label)) sidecar.copies.push({ label, at: now.toISOString() })
  for (const path of sidecarPaths) writeFileAtomic(path, JSON.stringify(sidecar, null, 2) + '\n', 0o644)
  return sidecar.copies
}

/** Add the instance id to a sidecar once it is known. The ciphertext is untouched. */
export function annotateInstance({ sidecarPaths, instanceId }) {
  const sidecar = readSidecar(sidecarPaths[0])
  if (sidecar.instanceId === instanceId) return
  if (sidecar.instanceId && sidecar.instanceId !== instanceId) {
    throw new StackError('BACKUP_CONFLICT', `${sidecarPaths[0]} already names instance ${sidecar.instanceId}.`)
  }
  for (const path of sidecarPaths) writeFileAtomic(path, JSON.stringify({ ...sidecar, instanceId }, null, 2) + '\n', 0o644)
}

/**
 * Decrypt an artifact with the caller's own keyring: on the offline recovery
 * machine, or a machine that has been given the recovery private key. Used
 * by `recover --from-backup` only.
 */
export function decryptArtifact(file, { exec = run, platform = process.platform, gpg = process.env.KORAS_GPG ?? 'gpg' } = {}) {
  const style = gpgPathStyle({ exec, platform, gpg })
  const decrypted = exec(gpg, ['--batch', '--decrypt', toGpgPath(file, style)])
  if (decrypted.status !== 0) {
    throw new StackError('BACKUP_DECRYPT', `gpg could not decrypt ${basename(file)}.`, 'Run this on a machine whose keyring holds the recovery private key.')
  }
  return decrypted.stdout
}
