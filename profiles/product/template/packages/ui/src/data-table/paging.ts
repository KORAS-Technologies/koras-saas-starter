/**
 * Where one page of rows starts and stops, and what the pager says about it.
 *
 * Pure, and in its own module for the reason `settings/value.ts` is: this
 * package has no test runner, and paging arithmetic is the kind of code that is
 * obviously right and off by one. The starter's own suite imports and executes
 * it.
 *
 * Every function here tolerates nonsense, because its inputs come from a
 * customer's stored settings and a URL. A page number of `-3`, a size of zero
 * and an options list holding `"fifty"` all have to produce a table, not a
 * stack trace: a settings framework that can render a broken page is worse than
 * no settings framework, since the broken page is the one nobody can fix
 * without a deploy.
 */

/** The default when nothing resolves: the number ADR 0007 fixes. */
export const DEFAULT_PAGE_SIZE = 50

/** What the size control offers when nothing resolves. */
export const DEFAULT_PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 250] as const

/**
 * The bounds a page size is held to, matching `grid.pageSize` in the catalogue.
 *
 * Duplicated here rather than fetched, and the generator's structural test
 * keeps the two level. The component has to bound a value that reached it from
 * a prop as well as one that came through the API, and only the API's was
 * checked against the definition.
 */
export const MIN_PAGE_SIZE = 10
export const MAX_PAGE_SIZE = 500

export interface Paging {
  /** 1-based, clamped into range. */
  page: number
  /** Rows per page, bounded; equal to `total` when paging is off. */
  size: number
  /** At least 1, so "page 1 of 1" is what an empty table says. */
  pages: number
  /** Index of the first row on this page, for `slice`. */
  start: number
  /** Index one past the last row on this page, for `slice`. */
  end: number
  /** 1-based position of the first row, for a person. `0` when there are none. */
  from: number
  /** 1-based position of the last row, for a person. `0` when there are none. */
  to: number
  total: number
}

/**
 * One page's bounds, from a row count, a requested page and a size.
 *
 * Three behaviours worth stating, because each is a decision rather than an
 * accident.
 *
 * *An empty table is page 1 of 1, showing 0 to 0.* Not "page 1 of 0", which
 * reads as a fault, and not "showing 1 to 0 of 0", which is what a naive
 * `start + 1` produces and which people report as a bug.
 *
 * *A page past the end lands on the last page, not on nothing.* Somebody who
 * was on page 9 when a colleague deleted rows should see the end of the list
 * rather than an empty grid that looks like the data is gone.
 *
 * *A size of zero or less means one page of everything.* That is how
 * `grid.paginationEnabled = false` is expressed, so the component has one code
 * path rather than a branch that skips the pager and another that skips the
 * slice.
 */
export function paginate(total: number, requestedPage: number, requestedSize: number): Paging {
  const rows = Math.max(0, Math.floor(total) || 0)
  const size = requestedSize > 0 ? Math.floor(requestedSize) : rows

  // `|| 1` for the unpaged case with no rows, where `size` is 0 and the
  // division is NaN. A table with no rows still has one page.
  const pages = size > 0 ? Math.max(1, Math.ceil(rows / size)) : 1
  const page = clampPage(requestedPage, pages)

  const start = size > 0 ? (page - 1) * size : 0
  const end = size > 0 ? Math.min(rows, start + size) : rows

  return {
    page,
    size,
    pages,
    start,
    end,
    // Zero rather than `start + 1` when the page is empty: "showing 1 to 0"
    // is the off-by-one everybody writes once.
    from: rows === 0 ? 0 : start + 1,
    to: end,
    total: rows,
  }
}

/** A page number held inside the range, whatever arrived. */
export function clampPage(page: number, pages: number): number {
  if (!Number.isFinite(page)) return 1
  return Math.min(Math.max(1, Math.floor(page)), Math.max(1, pages))
}

/** A page size held inside the bounds the catalogue declares. */
export function clampSize(size: number): number {
  if (!Number.isFinite(size)) return DEFAULT_PAGE_SIZE
  return Math.min(Math.max(MIN_PAGE_SIZE, Math.floor(size)), MAX_PAGE_SIZE)
}

/**
 * The sizes the control offers, given what an organisation configured.
 *
 * `grid.pageSizeOptions` is a list of strings, because a `STRING_LIST` is the
 * only list type that round-trips cleanly through `jsonb` and a `<select>`.
 * This is where they become numbers, and where a list that cannot be used
 * becomes one that can:
 *
 * - anything that is not a positive whole number is dropped, so one bad entry
 *   costs one option rather than the control;
 * - the size actually in effect is always offered, because a select whose
 *   current value is not among its options renders as though nothing is
 *   selected, and a person then cannot get back to it;
 * - duplicates collapse and the result is ascending, so two administrators
 *   configuring the same list in different orders get the same control.
 *
 * An empty or entirely unusable list falls back to the defaults rather than
 * rendering a control with one option in it.
 */
export function sizeOptions(configured: readonly string[], inEffect: number): number[] {
  const parsed = configured
    .map((entry) => Number.parseInt(entry, 10))
    .filter((value) => Number.isFinite(value) && value > 0)

  const usable = parsed.length > 0 ? parsed : [...DEFAULT_PAGE_SIZE_OPTIONS]
  return [...new Set([...usable, inEffect])].sort((a, b) => a - b)
}
