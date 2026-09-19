/**
 * The words the table needs, supplied by the surface that renders it.
 *
 * Passed in rather than translated here, which is the convention every
 * component in this package follows — `ReportTable` takes `ReportingLabels` for
 * the same reason. A shared component that reached for a translator would need
 * the catalogue in every bundle that imports it, and `product-frontend.test.ts`
 * asserts that no component in this package carries a sentence of English.
 *
 * Two of them are functions rather than templates with placeholders. "Showing 1
 * to 50 of 312" and "Page 1 of 7" put their numbers in different places in
 * different languages, and a function lets a catalogue decide where without
 * this file knowing. It also makes the plural somebody's problem who can
 * actually solve it.
 */
export interface DataTableLabels {
  /** Names the pager landmark, e.g. "Pagination". */
  pagination: string
  rowsPerPage: string
  previous: string
  next: string
  showing: (from: number, to: number, total: number) => string
  page: (page: number, pages: number) => string
}
