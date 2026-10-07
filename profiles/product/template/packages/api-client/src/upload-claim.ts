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
 * development origin does not, and WebCrypto has no incremental hash: the file is read into
 * memory once. That is the cost of a claim that is checked end to end; the API's size ceiling
 * is what bounds it.
 */

/** The browser could not take the SHA-256 an upload now requires. */
export class ChecksumUnavailableError extends Error {
  constructor(reason: string) {
    super(`This file cannot be uploaded because its checksum could not be calculated (${reason}).`)
    this.name = 'ChecksumUnavailableError'
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
 * is no `crypto.subtle` or the bytes cannot be read or hashed, and the caller must stop.
 * `subtle` is for a test to say what a browser would: `null` is "there is none" (an omitted
 * argument is the page's own `crypto.subtle`).
 */
export async function digestOf(
  file: Blob,
  subtle: DigestProvider | null | undefined = globalThis.crypto?.subtle,
): Promise<string> {
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
