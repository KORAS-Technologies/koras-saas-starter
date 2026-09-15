import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  PLATFORM_ASSET_MAX_BYTES,
  PlatformAssetError,
  fetchPlatformAsset,
} from './index.js'

/**
 * What this product will and will not fetch on a customer's behalf.
 *
 * The URL under test is one a customer typed into the Control Plane's portal.
 * The platform checked it began with `https://` and nothing else, so each
 * refusal below is a thing the platform lets through and this product does
 * not: a redirect to somewhere else, a page instead of an image, an image
 * the size of a disk, a server that never answers.
 */

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const URL_OK = 'https://assets.platform.example/acme/logo.png'

function answering(init: {
  status?: number
  headers?: Record<string, string>
  body?: BodyInit | null
}): { fetchImpl: typeof fetch; calls: Array<{ url: string; init: RequestInit }> } {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const fetchImpl: typeof fetch = async (input, requestInit) => {
    calls.push({ url: String(input), init: requestInit ?? {} })
    return new Response(init.body ?? null, {
      status: init.status ?? 200,
      headers: init.headers ?? {},
    })
  }
  return { fetchImpl, calls }
}

async function refusal(promise: Promise<unknown>): Promise<PlatformAssetError> {
  try {
    await promise
  } catch (error) {
    assert.ok(error instanceof PlatformAssetError, String(error))
    return error
  }
  assert.fail('expected a refusal')
}

test('an image is fetched without following anything and handed back whole', async () => {
  const { fetchImpl, calls } = answering({
    headers: { 'content-type': 'image/png; charset=binary', etag: '"v1"' },
    body: PNG,
  })
  const result = await fetchPlatformAsset(URL_OK, { fetchImpl, ifNoneMatch: '"v0"' })

  assert.equal(result.status, 'ok')
  if (result.status !== 'ok') return
  assert.deepEqual(new Uint8Array(result.body), PNG)
  assert.equal(result.contentType, 'image/png')
  assert.equal(result.etag, '"v1"')

  assert.equal(calls.length, 1)
  assert.equal(calls[0]?.url, URL_OK)
  assert.equal(calls[0]?.init.redirect, 'manual')
  assert.equal(calls[0]?.init.cache, 'no-store')
  assert.equal((calls[0]?.init.headers as Record<string, string>)['If-None-Match'], '"v0"')
})

test('an unchanged image is reported as such rather than re-read', async () => {
  const { fetchImpl } = answering({ status: 304, headers: { etag: '"v1"' } })
  assert.deepEqual(await fetchPlatformAsset(URL_OK, { fetchImpl, ifNoneMatch: '"v1"' }), {
    status: 'unchanged',
    etag: '"v1"',
  })
})

test('anything but https is refused before any request is made', async () => {
  for (const url of [
    'http://assets.platform.example/logo.png',
    'ftp://assets.platform.example/logo.png',
    'file:///etc/passwd',
    '/brand/logo.png',
    'not a url',
  ]) {
    const { fetchImpl, calls } = answering({ headers: { 'content-type': 'image/png' }, body: PNG })
    const error = await refusal(fetchPlatformAsset(url, { fetchImpl }))
    assert.equal(error.reason, 'not-https', url)
    assert.equal(calls.length, 0, url)
  }
})

test('a redirect is a URL nobody validated, and is refused', async () => {
  for (const status of [301, 302, 303, 307, 308]) {
    const { fetchImpl } = answering({ status, headers: { location: 'https://elsewhere.example/x' } })
    const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl }))
    assert.equal(error.reason, 'redirect', String(status))
  }
})

test('an upstream failure is reported as one', async () => {
  for (const status of [400, 403, 404, 500, 503]) {
    const { fetchImpl } = answering({ status, headers: { 'content-type': 'image/png' } })
    const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl }))
    assert.equal(error.reason, 'upstream-status', String(status))
  }
})

test('only an image content type may be served from this origin', async () => {
  for (const type of ['text/html', 'application/javascript', 'application/octet-stream', '']) {
    const { fetchImpl } = answering({ headers: type ? { 'content-type': type } : {}, body: PNG })
    const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl }))
    assert.equal(error.reason, 'content-type', type)
  }
  // The type is read, not the file. A PNG served as HTML is HTML to a browser.
  const { fetchImpl } = answering({ headers: { 'content-type': 'image/svg+xml' }, body: '<svg/>' })
  assert.equal((await fetchPlatformAsset(URL_OK, { fetchImpl })).status, 'ok')
})

test('a declared size over the cap is refused without reading a byte', async () => {
  // A zero high-water mark, or the stream pulls a chunk on construction and
  // the flag says nothing about who asked for it.
  let read = false
  const body = new ReadableStream<Uint8Array>(
    {
      pull(controller) {
        read = true
        controller.enqueue(PNG)
        controller.close()
      },
    },
    { highWaterMark: 0 },
  )
  const { fetchImpl } = answering({
    headers: { 'content-type': 'image/png', 'content-length': String(PLATFORM_ASSET_MAX_BYTES + 1) },
    body,
  })
  const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl }))
  assert.equal(error.reason, 'too-large')
  assert.equal(read, false)
})

test('a body that outgrows the cap is refused where it does, not after', async () => {
  // No content-length at all, and 64 KiB chunks past a 100 KiB cap: the
  // refusal has to come from counting, and it has to stop the read.
  let pulled = 0
  const chunk = new Uint8Array(64 * 1024)
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulled += 1
      controller.enqueue(chunk)
    },
  })
  const { fetchImpl } = answering({ headers: { 'content-type': 'image/png' }, body })
  const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl, maxBytes: 100 * 1024 }))
  assert.equal(error.reason, 'too-large')
  assert.ok(pulled <= 3, `read ${String(pulled)} chunks past the cap`)
})

test('a server that never answers is abandoned', async () => {
  const fetchImpl: typeof fetch = (_input, init) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => {
        reject(new DOMException('aborted', 'AbortError'))
      })
    })
  const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl, timeoutMs: 20 }))
  assert.equal(error.reason, 'timeout')
})

test('a network failure is a network failure, not a timeout', async () => {
  const fetchImpl: typeof fetch = async () => {
    throw new TypeError('fetch failed')
  }
  const error = await refusal(fetchPlatformAsset(URL_OK, { fetchImpl }))
  assert.equal(error.reason, 'network')
})
