import { describe, expect, it } from 'vitest'
import {
  BASELINE_PREFIX,
  isHeldHere,
  parseSubmitted,
  same,
  valuesForCategory,
  type FormDefinition,
} from '../../../profiles/product/template/packages/ui/src/settings/form-values'

/**
 * The settings form logic, **executed** rather than read.
 *
 * Every other assertion about the SET-05 and SET-06 corrections is a substring
 * search over template text, and an independent review made the cost of that
 * concrete on 2026-09-21: change `same()` to `return true` and no setting can
 * be saved on either page, while all four of those assertions still pass and
 * the whole node suite stays green. `return false` restores the SET-05 defect
 * verbatim, equally invisibly.
 *
 * This file is why that is no longer true. It imports the real module — plain
 * TypeScript in `packages/ui`, with no generated import, which is the whole
 * reason the logic was moved there — and drives it with real `FormData`.
 *
 * Every test below fails under `same() => true`, under `same() => false`, or
 * under inverting `isHeldHere`. That is the property being bought, and it is
 * worth more than the count.
 */

const DEFS: FormDefinition[] = [
  { key: 'grid.pageSize', category: 'grid', data_type: 'integer' },
  { key: 'grid.rowDensity', category: 'grid', data_type: 'enum' },
  { key: 'grid.stickyHeader', category: 'grid', data_type: 'boolean' },
  { key: 'files.allowedExtensions', category: 'files', data_type: 'string_list' },
  { key: 'general.companyName', category: 'general', data_type: 'string' },
  { key: 'general.scale', category: 'general', data_type: 'decimal' },
]

const ALL = () => true

/**
 * A form as the browser would send it.
 *
 * **The real form emits a baseline for every field it draws**, so a fixture
 * that supplies baselines only for the fields a test is thinking about is not
 * a form the product ever produces — and the difference is not cosmetic: a
 * boolean with no baseline is correctly written as `false`, which showed up as
 * three confusing failures the first time this file was written. So the
 * default here is a complete set, and a test that wants a field to have no
 * baseline says so by passing `null` for it.
 */
function form(
  values: Record<string, string>,
  baselines: Record<string, string | null>,
): FormData {
  const data = new FormData()
  for (const [key, value] of Object.entries(values)) data.append(key, value)
  for (const [key, value] of Object.entries(baselines)) {
    if (value !== null) data.append(`${BASELINE_PREFIX}${key}`, value)
  }
  return data
}

/** Every field of a category, at the values a freshly rendered page would show. */
const RENDERED: Record<string, string> = {
  'grid.pageSize': '50',
  'grid.rowDensity': 'compact',
  'grid.stickyHeader': 'true',
  'files.allowedExtensions': 'pdf, csv',
  'general.companyName': 'Original',
  'general.scale': '1.5',
}

describe('valuesForCategory — SET-05, only what somebody changed', () => {
  it('writes the one field that moved and none of the others', () => {
    // The defect, exactly: a member opens Tables, changes the page size, and
    // saves. Every other control in the category submitted too, because each
    // renders with a defaultValue.
    const submitted = form(
      { 'grid.pageSize': '100', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'on' },
      { 'grid.pageSize': '50', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'true' },
    )

    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({ 'grid.pageSize': 100 })
  })

  it('writes nothing at all when nothing moved', () => {
    const submitted = form(
      { 'grid.pageSize': '50', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'on' },
      { 'grid.pageSize': '50', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'true' },
    )

    // An empty result is what makes the action skip the write entirely. If this
    // ever returns the category, SET-05 is back.
    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({})
  })

  it('writes everything when the form carries no baselines', () => {
    // An older cached page. The previous behaviour, and the safe direction.
    const submitted = form({ 'grid.pageSize': '100', 'grid.rowDensity': 'compact' }, {})
    // Deliberately no baselines at all, which is what `{}` means here.

    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({
      'grid.pageSize': 100,
      'grid.rowDensity': 'compact',
      // Absent from the form, and a boolean is decided by presence.
      'grid.stickyHeader': false,
    })
  })

  it('sees a checkbox being turned off, which submits nothing at all', () => {
    // The case that makes the walk go over definitions rather than over the
    // form. `stickyHeader` is simply not in the body.
    const submitted = form({}, { 'grid.stickyHeader': 'true' })

    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({
      'grid.stickyHeader': false,
    })
  })

  it('leaves a checkbox alone when it was already off and stayed off', () => {
    const submitted = form({}, { 'grid.stickyHeader': 'false' })
    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({})
  })

  it('touches only the category it was given', () => {
    const submitted = form(
      {
        'grid.pageSize': '100',
        'grid.rowDensity': 'compact',
        'grid.stickyHeader': 'on',
        'general.companyName': 'Changed',
      },
      RENDERED,
    )

    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({ 'grid.pageSize': 100 })
    expect(valuesForCategory(DEFS, 'general', submitted, ALL)).toEqual({
      'general.companyName': 'Changed',
    })
  })

  it('writes nothing for a field this page may not show', () => {
    // Only `grid.pageSize` moved, and this page does not offer it. An
    // unsurfaced setting must not be writable through a form that never
    // drew it.
    const submitted = form(
      { 'grid.pageSize': '100', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'on' },
      RENDERED,
    )
    const hidden = (definition: FormDefinition) => definition.key !== 'grid.pageSize'

    expect(valuesForCategory(DEFS, 'grid', submitted, hidden)).toEqual({})
  })

  it('compares a list by its entries rather than by identity', () => {
    const unchanged = form(
      { 'files.allowedExtensions': 'pdf, csv' },
      { 'files.allowedExtensions': 'pdf, csv' },
    )
    expect(valuesForCategory(DEFS, 'files', unchanged, ALL)).toEqual({})

    const changed = form(
      { 'files.allowedExtensions': 'pdf, csv, png' },
      { 'files.allowedExtensions': 'pdf, csv' },
    )
    expect(valuesForCategory(DEFS, 'files', changed, ALL)).toEqual({
      'files.allowedExtensions': ['pdf', 'csv', 'png'],
    })
  })

  it('compares a number by its value, not its spelling', () => {
    // `1.50` and `1.5` are the same decimal and must not read as a change.
    const submitted = form({ 'general.scale': '1.50' }, { 'general.scale': '1.5' })
    expect(valuesForCategory(DEFS, 'general', submitted, ALL)).toEqual({})
  })

  it('writes the value when the baseline is unusable rather than dropping it', () => {
    // A corrupt or stale baseline must not silently swallow a real change.
    const submitted = form(
      { 'grid.pageSize': '100', 'grid.rowDensity': 'compact', 'grid.stickyHeader': 'on' },
      { ...RENDERED, 'grid.pageSize': 'not-a-number' },
    )
    expect(valuesForCategory(DEFS, 'grid', submitted, ALL)).toEqual({ 'grid.pageSize': 100 })
  })

  it('never writes a key that was not submitted, whatever the baseline says', () => {
    // The security-relevant half: a tampered baseline can only ever cause a
    // key to be omitted, never added or altered.
    const submitted = form({}, { 'grid.pageSize': '999', 'general.companyName': 'Injected' })
    expect(valuesForCategory(DEFS, 'general', submitted, ALL)).toEqual({})
  })
})

describe('isHeldHere — SET-06, what "held here" means at each scope', () => {
  it('reads row presence at member scope, even when the value matches', () => {
    // A person who deliberately picks the value their organisation already has
    // has still chosen it, and their Reset must stay available.
    expect(isHeldHere(true, 'dark', 'dark', 'a-row-exists')).toBe(true)
    expect(isHeldHere(false, 'dark', 'dark', 'a-row-exists')).toBe(false)
  })

  it('reads difference at organisation scope, where every key has a row', () => {
    // Provisioning copies every organisation-scoped key in, so presence is
    // true of everything and says nothing.
    expect(isHeldHere(true, 'dark', 'dark', 'differs-from-inherited')).toBe(false)
    expect(isHeldHere(true, 'dark', 'light', 'differs-from-inherited')).toBe(true)
  })

  it('never reports held when the scope holds no row, under either rule', () => {
    expect(isHeldHere(false, undefined, 'light', 'a-row-exists')).toBe(false)
    expect(isHeldHere(false, undefined, 'light', 'differs-from-inherited')).toBe(false)
  })

  it('distinguishes the two rules on the case that separates them', () => {
    // If these two ever agree, one of the pages is using the wrong rule.
    const held = (rule: 'a-row-exists' | 'differs-from-inherited') =>
      isHeldHere(true, 50, 50, rule)
    expect(held('a-row-exists')).not.toBe(held('differs-from-inherited'))
  })
})

describe('parseSubmitted and same', () => {
  it('decides a boolean by presence, and reads a baseline spelling', () => {
    const toggle = DEFS[2]!
    expect(parseSubmitted(toggle, null)).toBe(false)
    expect(parseSubmitted(toggle, 'on')).toBe(true)
    expect(parseSubmitted(toggle, 'true')).toBe(true)
    expect(parseSubmitted(toggle, 'false')).toBe(false)
  })

  it('refuses an object rather than storing "[object Object]"', () => {
    const object: FormDefinition = { key: 'x.config', category: 'general', data_type: 'object' }
    expect(parseSubmitted(object, '[object Object]')).toBeUndefined()
  })

  it('treats null and undefined as the same absence', () => {
    expect(same(null, undefined)).toBe(true)
    expect(same(0, null)).toBe(false)
    expect(same('', null)).toBe(false)
  })
})
