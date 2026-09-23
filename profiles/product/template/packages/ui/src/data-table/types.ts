/**
 * The words the table needs, supplied by the surface that renders it.
 *
 * Passed in rather than translated here, which is the convention every
 * component in this package follows — `ReportTable` takes `ReportingLabels` for
 * the same reason. A shared component that reached for a translator would need
 * the catalogue in every bundle that imports it, and `product-frontend.test.ts`
 * asserts that no component in this package carries a sentence of English.
 *
 * Four of them are templates with `{placeholder}`s rather than functions:
 * "Showing 1 to 50 of 312" and "Page 1 of 7" put their numbers in different
 * places in different languages, and a catalogue entry lets a translator
 * decide where without this file knowing. They are strings rather than
 * functions for the same reason every other label in this package is a
 * string — this component is a Client Component, its labels are built on the
 * server from the request's translator, and a function cannot cross that
 * boundary. `fill` substitutes the placeholders once the numbers are known,
 * on this side of it.
 */
export interface DataTableLabels {
  /** Names the pager landmark, e.g. "Pagination". */
  pagination: string
  rowsPerPage: string
  previous: string
  next: string
  /** `{from}`, `{to}`, `{total}` */
  showing: string
  /** `{page}`, `{pages}` */
  page: string
  /** Names one header's move control, e.g. "Move Amount left". A column's name
   *  is in the label because "Move left" repeated across nine headers is nine
   *  identical controls to a screen reader. `{column}` */
  moveColumnLeft: string
  moveColumnRight: string
}
