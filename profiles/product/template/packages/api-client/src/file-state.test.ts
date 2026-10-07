import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  POLL_DEADLINE_MS,
  POLL_MAX_MS,
  RELEASE_REFUSALS,
  anyScanning,
  availabilityOf,
  pollDelay,
  type Releasable,
} from './file-state.js'

/**
 * The page's reading of a file's release state (ADR 0013, `secure_files`).
 *
 * One claim, from every angle: the only way to `available` is the server
 * saying so *and* the stored verdict agreeing, and everything else -- every
 * state the page knows and every one it does not -- is not available.
 */

const read = (content_available: unknown, scan_status: unknown) =>
  availabilityOf({ content_available, scan_status } as Releasable)

test('only a server-released clean file is available', () => {
  assert.equal(read(true, 'clean'), 'available')
})

test('a pending file is being checked, and is never available', () => {
  assert.equal(read(false, 'pending'), 'scanning')
})

test('skipped, infected, missing and unrecognised states are unavailable, not scanning', () => {
  for (const scan of ['skipped', 'infected', null, undefined, '', 'CLEAN', 'clean ', 'quarantined', 0, {}]) {
    assert.equal(read(false, scan), 'unavailable', String(scan))
  }
})

test('a file the server did not release is not available whatever its verdict says', () => {
  assert.equal(read(false, 'clean'), 'unavailable')
  assert.equal(read(undefined, 'clean'), 'unavailable', 'an API that predates the field')
  assert.equal(read(null, 'clean'), 'unavailable')
})

test('content_available must be exactly true: truthy lookalikes do not release', () => {
  for (const value of ['true', 1, 'yes', {}, []]) {
    assert.equal(read(value, 'clean'), 'unavailable', String(value))
  }
})

test('a contradiction reads as unavailable, never as available', () => {
  for (const scan of ['pending', 'skipped', 'infected', null, 'whatever']) {
    assert.equal(read(true, scan), 'unavailable', String(scan))
  }
})

test('anyScanning is true only while a file is awaiting its check', () => {
  const clean: Releasable = { content_available: true, scan_status: 'clean' }
  const pending: Releasable = { content_available: false, scan_status: 'pending' }
  const skipped: Releasable = { content_available: false, scan_status: 'skipped' }
  assert.equal(anyScanning([]), false)
  assert.equal(anyScanning([clean, skipped]), false)
  assert.equal(anyScanning([clean, pending]), true)
})

test('both refusal codes the download route gives for an unreleasable file are recognised', () => {
  assert.deepEqual([...RELEASE_REFUSALS].sort(), ['file_quarantined', 'file_scan_pending'])
})

test('the refresh delay grows, is capped, and the whole wait has a deadline', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 50].map(pollDelay), [10_000, 20_000, 40_000, 60_000, 60_000, 60_000])
  assert.equal(pollDelay(-3), 10_000)
  assert.equal(pollDelay(1000), POLL_MAX_MS)
  let waited = 0
  let polls = 0
  for (let attempt = 0; waited < POLL_DEADLINE_MS; attempt += 1) {
    waited += pollDelay(attempt)
    polls += 1
  }
  assert.ok(polls <= 40, `a page open to the deadline reads the list ${polls} times`)
})
