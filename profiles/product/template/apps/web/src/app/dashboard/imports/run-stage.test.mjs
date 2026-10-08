import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { STAGES, formatWhen, runIdFromSearch, stageOf, stepState } from './run-stage.ts'

const at = (status, over = {}) => stageOf({ status, committedBy: null, reviewed: false, remap: false, ...over })

test('a stage is derived from the persisted state, so a refresh lands where the run really is', () => {
  assert.equal(at(null), 'upload')
  assert.equal(at('created'), 'map')
  assert.equal(at('mapped'), 'map')
  assert.equal(at('validating'), 'validate')
  assert.equal(at('validation_failed'), 'validate')
  assert.equal(at('validated'), 'review')
  assert.equal(at('commit_requested', { committedBy: 'x' }), 'processing')
  assert.equal(at('committing', { committedBy: 'x' }), 'processing')
  assert.equal(at('committed', { committedBy: 'x' }), 'results')
})

test('Confirm needs a person to have gone through Review, and going back or remapping leaves it', () => {
  assert.equal(at('validated', { reviewed: true }), 'confirm')
  assert.equal(at('validated', { remap: true, reviewed: true }), 'map')
  assert.equal(at('validation_failed', { remap: true }), 'map')
  // Only a checked run can be at Confirm: nothing else is ever committable.
  for (const status of ['created', 'mapped', 'validating', 'validation_failed', 'committed', 'cancelled', 'failed']) {
    assert.notEqual(at(status, { reviewed: true }), 'confirm', status)
  }
})

test('a failed run is placed by whether anybody confirmed it; a cancelled or unknown one is placed nowhere', () => {
  assert.equal(at('failed'), 'validate')
  assert.equal(at('failed', { committedBy: 'x' }), 'processing')
  assert.equal(at('cancelled'), null)
  assert.equal(at('some_future_state'), null)
})

test('steps before the current one are done, the current one is current, a null stage marks nothing', () => {
  assert.deepEqual(STAGES.map((s) => stepState(s, 'review')), ['done', 'done', 'done', 'current', 'todo', 'todo', 'todo'])
  assert.deepEqual(STAGES.map((s) => stepState(s, null)), STAGES.map(() => 'todo'))
})

test('a stored UTC instant is shown in a readable form, never as the raw ISO string, and the first render is UTC', () => {
  const iso = '2026-10-08T13:55:17.448663Z'
  const utc = formatWhen(iso, 'en', 'UTC')
  assert.ok(utc.endsWith(' UTC'))
  assert.ok(utc.includes('2026'))
  assert.equal(utc.includes('T13'), false)
  assert.equal(formatWhen('not a date', 'en'), 'not a date')
  assert.equal(formatWhen(iso, 'definitely-not-a-locale-xx-yy-zz'), formatWhen(iso, 'en') === '' ? '' : formatWhen(iso, 'definitely-not-a-locale-xx-yy-zz'))
})

test('only a canonical run id in the address is a run', () => {
  const id = '5b0e6f0e-7a54-4a43-9c4f-4a0f6b7c3d11'
  assert.equal(runIdFromSearch('?run=' + id), id)
  assert.equal(runIdFromSearch('?run=' + id.toUpperCase()), id)
  for (const bad of ['', '?run=', '?run=1', '?run=urn:uuid:' + id, '?run=' + id + 'x', '?other=' + id, '?run=../../x']) {
    assert.equal(runIdFromSearch(bad), null, bad)
  }
})
