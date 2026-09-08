import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parsePublicPlans } from './index.js'

/**
 * The public catalogue, as the pricing section and the signup form read it.
 *
 * `parsePublicPlans` is the boundary between the platform's anonymous plans
 * endpoint and this product. It has one job beyond shape-checking: a Control
 * Plane from before the billing work answers two fields, and the product has
 * to read that as what it was selling -- a free trial with one seat -- rather
 * than as a plan with unknowable prices.
 */

test('a priced plan comes through with its references and bounds', () => {
  const [plan] = parsePublicPlans([
    {
      code: 'starter',
      name: 'Starter',
      price_id_month: 'pri_month',
      price_id_year: 'pri_year',
      min_seats: 2,
      max_seats: 50,
    },
  ])
  assert.deepEqual(plan, {
    code: 'starter',
    name: 'Starter',
    price_id_month: 'pri_month',
    price_id_year: 'pri_year',
    min_seats: 2,
    max_seats: 50,
  })
})

test('an older platform answering two fields is a free trial with one seat', () => {
  const [plan] = parsePublicPlans([{ code: 'trial', name: 'Trial' }])
  assert.equal(plan?.price_id_month, null)
  assert.equal(plan?.price_id_year, null)
  assert.equal(plan?.min_seats, 1)
  assert.equal(plan?.max_seats, null)
})

test('anything that is not a list of plans is an empty catalogue', () => {
  for (const raw of [null, undefined, 'starter', 42, {}, { plans: [] }]) {
    assert.deepEqual(parsePublicPlans(raw), [], JSON.stringify(raw ?? null))
  }
  // A row without a code is not a plan and is dropped, not guessed at.
  assert.deepEqual(parsePublicPlans([{ name: 'Nameless' }, null, 'x']), [])
})
