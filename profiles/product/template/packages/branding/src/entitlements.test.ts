import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { NO_ENTITLEMENTS, isEntitled, parseEntitlements } from './index.js'

/**
 * What the platform's answer is allowed to become.
 *
 * `parseEntitlements` is the boundary between an API this product does not own
 * and every plan gate in the sidebar. The half worth arguing is not the happy
 * path: it is that nothing malformed can produce a *partial* set. A plan
 * missing three of its features looks like an answer, and a module gated on one
 * of the three would be hidden with no sign that anything went wrong.
 *
 * The field names below are the portal API's -- `plan_code`, `code`,
 * `limit_value`. They are asserted here because a rename on either side is
 * otherwise a silent no-op: every row would be skipped and the customer would
 * simply appear to have bought nothing.
 */

const ANSWER = {
  product_code: 'example',
  plan_code: 'growth',
  entitlements: [
    { code: 'advanced_reporting', name: 'Advanced reporting', enabled: true, limit_value: null },
    { code: 'seats', name: 'Seats', enabled: true, limit_value: 25 },
    { code: 'sso', name: 'Single sign-on', enabled: false, limit_value: null },
  ],
}

test('a plan resolves to its granted features', () => {
  const set = parseEntitlements(ANSWER)

  assert.equal(set.resolved, true)
  assert.equal(set.plan, 'growth')
  assert.equal(isEntitled(set, 'advanced_reporting'), true)
  assert.equal(set.features.seats?.limit, 25)
  // Present and off is not the same as absent, and both mean not entitled.
  assert.equal(isEntitled(set, 'sso'), false)
  assert.equal(isEntitled(set, 'never_defined'), false)
})

test('a plan the platform did not name still resolves', () => {
  // A subscription with no plan is a real state -- an override-only customer --
  // and it grants what it grants. Unresolved would be a claim that the read
  // failed, which it did not.
  const set = parseEntitlements({ ...ANSWER, plan_code: null })
  assert.equal(set.resolved, true)
  assert.equal(set.plan, null)
  assert.equal(isEntitled(set, 'advanced_reporting'), true)
})

test('an answer with no entitlements array is unresolved, not empty', () => {
  for (const raw of [null, undefined, 'growth', 42, [], {}, { entitlements: 'all' }]) {
    assert.deepEqual(parseEntitlements(raw), NO_ENTITLEMENTS, JSON.stringify(raw ?? null))
  }
})

test('a row that cannot be understood is dropped, not guessed at', () => {
  const set = parseEntitlements({
    plan_code: 'growth',
    entitlements: [
      null,
      'advanced_reporting',
      ['advanced_reporting'],
      { name: 'No code at all', enabled: true },
      { code: '', enabled: true },
      { code: 'kept', enabled: true, limit_value: 3 },
    ],
  })

  assert.deepEqual(Object.keys(set.features), ['kept'])
  assert.equal(isEntitled(set, 'kept'), true)
})

test('enabled must be said, and a limit must be a number', () => {
  const set = parseEntitlements({
    plan_code: 'growth',
    entitlements: [
      { code: 'absent' },
      { code: 'stringly', enabled: 'true' },
      { code: 'off', enabled: false },
      { code: 'unbounded', enabled: true, limit_value: null },
      { code: 'stringly_limited', enabled: true, limit_value: '25' },
    ],
  })

  // Anything but `true` is off. A paid feature must not be obtainable by
  // sending a field the platform never sends.
  assert.equal(isEntitled(set, 'absent'), false)
  assert.equal(isEntitled(set, 'stringly'), false)
  assert.equal(isEntitled(set, 'off'), false)
  // A limit that is not a number is no limit rather than a limit of zero: the
  // gate is `enabled`, and inventing a bound here would deny a granted feature.
  assert.equal(set.features.unbounded?.limit, null)
  assert.equal(set.features.stringly_limited?.limit, null)
  assert.equal(isEntitled(set, 'stringly_limited'), true)
})

test('an unresolved set entitles nothing at all', () => {
  assert.equal(NO_ENTITLEMENTS.resolved, false)
  assert.equal(isEntitled(NO_ENTITLEMENTS, 'advanced_reporting'), false)
})
