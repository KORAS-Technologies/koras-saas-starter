import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  ChecksumUnavailableError,
  digestOf,
  isCanonicalSha256,
  SHA256_HEX,
  type DigestProvider,
} from './upload-claim.js'

/**
 * The claim a first-party client sends with every upload ticket in a `secure_files` product.
 *
 * What is asserted is what the API would otherwise refuse or, worse, accept: the digest is
 * the SHA-256 of the bytes and nothing else, it is lowercase 64-hex, and when it cannot be
 * taken the function throws rather than returning something the caller might send.
 */

// FIPS 180-2 test vectors.
const ABC = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
const EMPTY = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'

test('the digest is the SHA-256 of the bytes, lowercase, 64 hex characters', async () => {
  assert.equal(await digestOf(new Blob(['abc'])), ABC)
  assert.match(await digestOf(new Blob(['abc'])), SHA256_HEX)
})

test('an empty file has a digest too, and it is the well-known one', async () => {
  assert.equal(await digestOf(new Blob([])), EMPTY)
})

test('the digest depends on every byte', async () => {
  const a = await digestOf(new Blob([new Uint8Array([1, 2, 3, 4])]))
  const b = await digestOf(new Blob([new Uint8Array([1, 2, 3, 5])]))
  assert.notEqual(a, b)
})

test('binary content is hashed as bytes, not as text', async () => {
  const bytes = new Uint8Array([0xff, 0xfe, 0x00, 0x80])
  const expected = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  const hex = Array.from(new Uint8Array(expected))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
  assert.equal(await digestOf(new Blob([bytes])), hex)
})

test('with no secure context there is no digest and the caller must stop', async () => {
  await assert.rejects(
    () => digestOf(new Blob(['abc']), null),
    (error: unknown) => {
      assert.ok(error instanceof ChecksumUnavailableError)
      assert.match((error as Error).message, /cannot be uploaded/)
      return true
    },
  )
})

test('a hash that fails is a refusal, never an empty claim', async () => {
  const broken: DigestProvider = {
    digest: async () => {
      throw new Error('out of memory')
    },
  }
  await assert.rejects(() => digestOf(new Blob(['abc']), broken), ChecksumUnavailableError)
})

test('a file that cannot be read is a refusal, never an empty claim', async () => {
  const unreadable = {
    arrayBuffer: async () => {
      throw new Error('the file changed on disk')
    },
  } as unknown as Blob
  await assert.rejects(() => digestOf(unreadable), ChecksumUnavailableError)
})

test('an answer that is not a SHA-256 is not sent', async () => {
  const short: DigestProvider = { digest: async () => new Uint8Array([1, 2, 3]).buffer }
  await assert.rejects(() => digestOf(new Blob(['abc']), short), ChecksumUnavailableError)
})

test('the canonical form is what the API accepts: lowercase, 64, hex, no padding', () => {
  assert.equal(isCanonicalSha256(ABC), true)
  assert.equal(isCanonicalSha256(ABC.toUpperCase()), false)
  assert.equal(isCanonicalSha256(ABC.slice(1)), false)
  assert.equal(isCanonicalSha256(ABC + '0'), false)
  assert.equal(isCanonicalSha256(' ' + ABC), false)
  assert.equal(isCanonicalSha256(ABC.replace('b', 'g')), false)
  assert.equal(isCanonicalSha256(''), false)
})
