import type { ResolvedSetting, SettingValue } from './types'

/**
 * Which value a component actually uses, given what the server resolved.
 *
 * Pure, and in its own module rather than inside the provider, for one reason:
 * `packages/ui` has no test runner in this template — it is typechecked and
 * exercised in a browser by Playwright, and nothing in it is unit-tested. A
 * decision this small and this easy to get subtly wrong should be testable
 * without a DOM, so it lives here and `product-settings.test.ts` imports it
 * directly.
 *
 * Two rules, and the second is the one worth having.
 *
 * *Nothing resolved means the fallback.* A component rendered outside the
 * signed-in area, or before the first load, or while the API was unreachable,
 * uses the value it would have used anyway.
 *
 * *A value of the wrong shape means the fallback too.* A definition can change
 * under a value that was valid when it was written — an integer setting made
 * an enum, say — and the row survives until somebody writes it again. Trusting
 * it would mean a table asked to draw `"comfortable"` rows per page. Falling
 * back is not hiding the problem: `EffectiveSettings.skipped` carries what the
 * resolver refused, and this is the narrower case where the server accepted a
 * value and this particular component cannot use it.
 *
 * `chooseValue` is the whole decision and is not overloaded; `settingValue` is
 * the same function with the signatures a caller wants. Both exist so the hook
 * in `provider.tsx` can delegate to the plain one rather than casting its way
 * through its own overloads.
 */
export function chooseValue(
  resolved: ResolvedSetting | undefined,
  fallback: SettingValue,
): SettingValue {
  if (resolved === undefined) return fallback
  return sameShape(resolved.value, fallback) ? resolved.value : fallback
}

/**
 * The same, overloaded so a literal fallback does not become the whole type.
 *
 * `settingValue(resolved, 'comfortable')` with a single generic signature
 * infers `T` as the literal `'comfortable'`, so the caller is handed a value
 * TypeScript believes can only ever be that one string -- and `density ===
 * 'compact'` two lines later is "a comparison with no overlap". The same
 * happens to `50`, where it goes unnoticed until somebody compares against a
 * page size.
 *
 * The overloads widen at the boundary: a boolean fallback yields `boolean`, a
 * number `number`, a string `string`. A caller that genuinely wants the narrow
 * type still has one, by writing it.
 *
 * Found on 2026-09-19 by building a generated product, which is the only thing
 * that compiles this package.
 */
export function settingValue(r: ResolvedSetting | undefined, fallback: boolean): boolean
export function settingValue(r: ResolvedSetting | undefined, fallback: number): number
export function settingValue(r: ResolvedSetting | undefined, fallback: string): string
export function settingValue(
  r: ResolvedSetting | undefined,
  fallback: readonly string[],
): readonly string[]
export function settingValue(
  r: ResolvedSetting | undefined,
  fallback: Record<string, unknown>,
): Record<string, unknown>
export function settingValue(
  resolved: ResolvedSetting | undefined,
  fallback: SettingValue,
): SettingValue {
  return chooseValue(resolved, fallback)
}

/**
 * Whether a resolved value is the same kind of thing as the fallback.
 *
 * `typeof` alone is not enough: an array is an `object` in JavaScript and so is
 * a settings object, and a component expecting a list of page sizes given a
 * `{}` would map over nothing and render an empty control rather than falling
 * back. Arrays are therefore decided first, in both directions.
 *
 * Deliberately shallow. This guards against a setting whose *type* changed, not
 * against a value whose contents are wrong — bounds and options are the
 * definition's job, checked in the API before the value was ever stored.
 */
export function sameShape(value: SettingValue, fallback: SettingValue): boolean {
  if (Array.isArray(fallback)) return Array.isArray(value)
  if (Array.isArray(value)) return false
  return typeof value === typeof fallback
}
