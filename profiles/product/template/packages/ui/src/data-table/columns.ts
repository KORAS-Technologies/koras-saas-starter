/**
 * A table's column widths and order, remembered per viewer.
 *
 * Pure and in its own module for the reason `paging.ts` is: this package has no
 * test runner, and "restore what the person arranged" is the kind of code that
 * is obviously right and silently drops a column. The starter's own suite
 * imports and executes it.
 *
 * ## Why this is browser storage rather than a setting
 *
 * `grid.rememberColumns` says *whether* to remember; it does not hold what was
 * remembered. Where a person dragged a column is a per-viewer, per-table,
 * per-device convenience, and putting it in `member_setting_values` would mean
 * a row per table per person, a write on every drag, and a settings page listing
 * arrangements nobody can read. So the switch is a setting and the arrangement
 * is `localStorage`.
 *
 * Every access is wrapped: a private window, blocked site data or a quota that
 * is full must leave a working table rather than a stack trace. A read that
 * fails is a table in its declared order, which is exactly right.
 *
 * ## What an arrangement may never do
 *
 * **It may not add, remove or rename a column.** Stored state is input the
 * component does not control — a stale entry from before a column was removed,
 * or one somebody edited by hand. `applyArrangement` treats it as a *hint about
 * order* over the columns the caller actually declared: anything unknown is
 * dropped, anything missing is appended in declared order, and the result is
 * always exactly the declared set. A column cannot disappear because a key
 * changed, and one cannot be conjured by editing storage.
 */

/** What a viewer arranged for one table. */
export interface Arrangement {
  /** Column keys, in the order they should appear. Unknown keys are ignored. */
  order?: readonly string[]
  /** Column key to width in pixels. Out-of-range values are ignored. */
  widths?: Readonly<Record<string, number>>
}

/** Narrower than this and a header is unreadable; wider and it is a page. */
export const MIN_COLUMN_WIDTH = 64
export const MAX_COLUMN_WIDTH = 960

const PREFIX = 'koras.table.'

/** Where one table's arrangement lives. Per table id, so two on a page differ. */
export function storageKey(tableId: string): string {
  return `${PREFIX}${tableId}`
}

/**
 * The declared columns in the order the viewer arranged them.
 *
 * Returns the **declared set**, always: same length, same members. Order is the
 * only thing the arrangement decides.
 */
export function applyArrangement<T extends { key: string }>(
  columns: readonly T[],
  arrangement: Arrangement | null,
): T[] {
  if (!arrangement?.order?.length) return [...columns]
  const byKey = new Map(columns.map((column) => [column.key, column]))
  const ordered: T[] = []
  for (const key of arrangement.order) {
    const column = byKey.get(key)
    // `delete` as we go, so a stored order naming the same key twice cannot
    // produce the same column twice.
    if (column && byKey.delete(key)) ordered.push(column)
  }
  // Whatever the arrangement did not mention keeps its declared position
  // relative to the rest — a column added in a release lands where the
  // developer put it rather than at the end of somebody's saved order.
  for (const column of columns) {
    if (byKey.has(column.key)) ordered.push(column)
  }
  return ordered
}

/** A width held inside the bounds, or nothing if it is not a usable number. */
export function clampWidth(width: number): number | null {
  if (!Number.isFinite(width)) return null
  const rounded = Math.round(width)
  if (rounded <= 0) return null
  return Math.min(Math.max(MIN_COLUMN_WIDTH, rounded), MAX_COLUMN_WIDTH)
}

/** An arrangement from whatever was stored, with everything unusable dropped. */
export function parseArrangement(raw: string | null): Arrangement | null {
  if (!raw) return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null) return null

  const source = value as { order?: unknown; widths?: unknown }
  const order = Array.isArray(source.order)
    ? source.order.filter((entry): entry is string => typeof entry === 'string')
    : undefined

  let widths: Record<string, number> | undefined
  if (typeof source.widths === 'object' && source.widths !== null) {
    widths = {}
    for (const [key, entry] of Object.entries(source.widths as Record<string, unknown>)) {
      const clamped = typeof entry === 'number' ? clampWidth(entry) : null
      if (clamped !== null) widths[key] = clamped
    }
  }

  if (!order?.length && !widths) return null
  return { order, widths }
}

/** Read one table's arrangement. Never throws; absent storage is `null`. */
export function readArrangement(tableId: string): Arrangement | null {
  try {
    return parseArrangement(globalThis.localStorage?.getItem(storageKey(tableId)) ?? null)
  } catch {
    return null
  }
}

/** Write one table's arrangement, or remove it when there is nothing to keep. */
export function writeArrangement(tableId: string, arrangement: Arrangement | null): void {
  try {
    const store = globalThis.localStorage
    if (!store) return
    if (!arrangement || (!arrangement.order?.length && !arrangement.widths)) {
      store.removeItem(storageKey(tableId))
      return
    }
    store.setItem(storageKey(tableId), JSON.stringify(arrangement))
  } catch {
    // A full quota or a private window. The table goes on working and the
    // arrangement lasts as long as the page, which is the honest outcome.
  }
}
