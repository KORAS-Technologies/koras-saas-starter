/**
 * The content claim an upload is authorized for (ADR 0013, `secure_files`).
 *
 * In a product generated with the capability the API refuses to issue an upload ticket
 * without `checksum_sha256`: exactly 64 lowercase hex characters, the SHA-256 of the bytes
 * about to be sent. It is bound to the file when the ticket is issued, signed into the upload
 * URL, never changed by the client afterwards, and the worker promotes an object to a final
 * key only if the bytes it reads back hash to it. So a first-party client has to compute it
 * *before* it asks for a ticket, and a file whose digest cannot be taken is not uploaded at
 * all -- nothing here, or on the server, substitutes one.
 *
 * Kept in this package, with no framework in it, so the same function serves the Files page,
 * the import panel and any later upload surface, and so it has a test of its own.
 *
 * `crypto.subtle` needs a secure context, which a deployed product always has and a plain-http
 * development origin does not, and WebCrypto has no incremental hash: the whole file is read
 * into memory once (and the browser may briefly hold a second copy while it hashes). That is
 * the cost of a claim that is checked end to end, and it is bounded HERE, not by the API.
 *
 * **The bound is `MAX_HASHABLE_BYTES`, 100 MiB.** It is the scan ceiling the clamd service is
 * built for (`SCAN_CEILING_BYTES` in the generated `core/secure_files.py`; the API's own
 * per-object limit is far larger and says nothing about what a browser tab can hold). A file
 * above it can never be scanned, so it could never be released; refusing it before it is read
 * into memory, with a sentence the person can act on, is the same outcome without a tab that
 * runs out of memory or an upload that is stored and held for ever. No dependency is added to
 * hash in pieces: a streaming SHA-256 is a new surface the claim would depend on, and the
 * ceiling makes it unnecessary.
 */

/** The most the browser will read into memory to hash, and so the most it will upload. */
export const MAX_HASHABLE_BYTES = 100 * 1024 * 1024

/** The browser could not take the SHA-256 an upload now requires. */
export class ChecksumUnavailableError extends Error {
  constructor(reason: string, message?: string) {
    super(
      message ??
        `This file cannot be uploaded because its checksum could not be calculated (${reason}).`,
    )
    this.name = 'ChecksumUnavailableError'
  }
}

/**
 * The file is above what the browser can check, so it fails closed before it is read.
 * A `ChecksumUnavailableError`, so every caller that already stops on one stops on this.
 */
export class FileTooLargeToCheckError extends ChecksumUnavailableError {
  constructor(limitBytes: number = MAX_HASHABLE_BYTES) {
    const megabytes = Math.floor(limitBytes / (1024 * 1024))
    super(
      'too large',
      `This file is larger than ${megabytes} MB, the most that can be checked and uploaded here, so it was not uploaded.`,
    )
    this.name = 'FileTooLargeToCheckError'
  }
}

/** Exactly what the API accepts as a claim: lowercase 64-hex. Uppercase is refused, not rewritten. */
export const SHA256_HEX = /^[0-9a-f]{64}$/

export function isCanonicalSha256(value: string): boolean {
  return SHA256_HEX.test(value)
}

/** The part of `SubtleCrypto` this needs, so a test can say what a browser would. */
export interface DigestProvider {
  digest(algorithm: 'SHA-256', data: ArrayBuffer): Promise<ArrayBuffer>
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * The SHA-256 of what is about to be sent, as the claim the API requires.
 *
 * Throws `ChecksumUnavailableError` -- never returns an empty or partial value -- when there
 * is no `crypto.subtle`, the bytes cannot be read or hashed, or the file is above
 * `MAX_HASHABLE_BYTES` (`FileTooLargeToCheckError`), and the caller must stop.
 * `subtle` is for a test to say what a browser would: `null` is "there is none" (an omitted
 * argument is the page's own `crypto.subtle`).
 */
export async function digestOf(
  file: Blob,
  subtle: DigestProvider | null | undefined = globalThis.crypto?.subtle,
  limitBytes: number = MAX_HASHABLE_BYTES,
): Promise<string> {
  // Before anything is read: a file past the ceiling is never loaded into memory.
  if (file.size > limitBytes) throw new FileTooLargeToCheckError(limitBytes)
  if (!subtle) throw new ChecksumUnavailableError('no secure context')
  let digest: string
  try {
    digest = toHex(new Uint8Array(await subtle.digest('SHA-256', await file.arrayBuffer())))
  } catch {
    throw new ChecksumUnavailableError('the file could not be read into memory')
  }
  // A provider that answered something that is not a SHA-256 is not a digest to send.
  if (!isCanonicalSha256(digest)) throw new ChecksumUnavailableError('the digest was malformed')
  return digest
}
