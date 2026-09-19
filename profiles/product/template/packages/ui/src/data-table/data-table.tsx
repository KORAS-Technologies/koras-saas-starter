'use client'

import { useMemo, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'
import { useSettingValue } from '../settings/provider'
import {
  DEFAULT_PAGE_SIZE,
  DEFAULT_PAGE_SIZE_OPTIONS,
  clampSize,
  paginate,
  sizeOptions,
} from './paging'
import type { DataTableLabels } from './types'

/**
 * The product's table, which pages itself from the customer's own settings.
 *
 * ```tsx
 * <KorasDataTable data={records} columns={columns} caption="Orders" labels={labels} />
 * ```
 *
 * That is the whole ordinary usage. How many rows it shows, whether it pages at
 * all, which sizes it offers, whether the header sticks and how tall the rows
 * are all come from `grid.*`, resolved once in the dashboard layout and read
 * from context. No page fetches a setting and no page passes one down.
 *
 * **An explicit prop always wins.** A screen with a legitimate local
 * requirement — a dense picker inside a dialog, a preview showing three rows —
 * passes `pageSize={3}` and the setting does not apply to that instance. The
 * order is prop, then setting, then the constant in `paging.ts`, and it is the
 * same order for every one of them.
 *
 * **What it honours today, as of 2026-09-19.** `grid.pageSize`,
 * `grid.pageSizeOptions`, `grid.paginationEnabled`, `grid.stickyHeader` and
 * `grid.rowDensity`. The other five `grid.*` settings are declared in the
 * catalogue and are not read here: `allowColumnResize` and `allowColumnReorder`
 * need interactions this component does not have yet, and the three `remember*`
 * settings describe persistence of state the table does not own — a filter and
 * a sort belong to the surface above it, which is where that state lives in the
 * Control Plane's toolbar too. Declaring them costs nothing and reserves the
 * vocabulary; reading them and doing nothing would be worse than not reading
 * them, because a setting that visibly does nothing teaches people the whole
 * framework is decorative.
 *
 * **Paging state is the component's, not the URL's.** A table that wrote its
 * page into the query string would fight the toolbar above it for the same
 * parameter, and two tables on one screen would fight each other. When a
 * surface wants a shareable page it lifts the state and passes `page` down;
 * that is the seam `rememberSort` will use when it arrives.
 */

export interface DataTableColumn<T> {
  /** Stable identity, and what lands in `data-column`. */
  key: string
  header: string
  cell: (row: T, index: number) => ReactNode
  align?: 'left' | 'right'
  /** A width class, e.g. `w-40`. A class rather than a number, so a column's
   * width is a design decision in the same vocabulary as everything else. */
  width?: string
  /** Hidden below this breakpoint, for a column that is detail rather than
   * identity. A table narrower than its content is worse than a shorter one. */
  hideBelow?: 'sm' | 'md' | 'lg'
}

const HIDE_BELOW = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
} as const

export function KorasDataTable<T>({
  data,
  columns,
  caption,
  labels,
  empty,
  emptyHint,
  rowKey,
  testId = 'data-table',
  className,
  pageSize,
  paginationEnabled,
  stickyHeader,
  rowDensity,
}: {
  data: readonly T[]
  columns: readonly DataTableColumn<T>[]
  /** Read out to somebody who arrived at the table by heading. Never decorative. */
  caption: string
  labels: DataTableLabels
  /** A sentence, not an empty grid. */
  empty: string
  emptyHint?: ReactNode
  rowKey?: (row: T, index: number) => string
  testId?: string
  className?: string
  /** Overrides `grid.pageSize` for this table alone. */
  pageSize?: number
  /** Overrides `grid.paginationEnabled`. */
  paginationEnabled?: boolean
  /** Overrides `grid.stickyHeader`. */
  stickyHeader?: boolean
  /** Overrides `grid.rowDensity`. */
  rowDensity?: 'comfortable' | 'compact'
}) {
  const settingSize = useSettingValue('grid.pageSize', DEFAULT_PAGE_SIZE)
  const settingPaging = useSettingValue('grid.paginationEnabled', true)
  const settingSticky = useSettingValue('grid.stickyHeader', true)
  const settingDensity = useSettingValue('grid.rowDensity', 'comfortable')
  // No type argument: `useSettingValue` is overloaded rather than generic, so
  // the list overload is chosen by the fallback and the result is widened to
  // `readonly string[]` rather than narrowed to the five defaults.
  const settingOptions = useSettingValue(
    'grid.pageSizeOptions',
    DEFAULT_PAGE_SIZE_OPTIONS.map(String),
  )

  const pages = paginationEnabled ?? settingPaging
  const sticky = stickyHeader ?? settingSticky
  const density = rowDensity ?? (settingDensity === 'compact' ? 'compact' : 'comfortable')

  // Clamped whether it arrived from a prop or a setting: the API checked the
  // setting against the definition, and nothing checked the prop.
  const resolvedSize = clampSize(pageSize ?? settingSize)

  // The size a person picked for this table, which outlives neither the page
  // nor the navigation. Changing it for good is `/dashboard/preferences`;
  // changing it here is for looking at this list right now.
  const [chosenSize, setChosenSize] = useState<number | null>(null)
  const [requestedPage, setRequestedPage] = useState(1)

  const size = pages ? (chosenSize ?? resolvedSize) : 0
  const paging = paginate(data.length, requestedPage, size)
  // Keyed on the size rather than on the `paging` object, which is rebuilt
  // every render and would make the memo do nothing but allocate.
  const options = useMemo(
    () => sizeOptions(settingOptions, paging.size),
    [settingOptions, paging.size],
  )

  const rows = pages ? data.slice(paging.start, paging.end) : data

  if (data.length === 0) {
    return (
      <div className={cn('rounded-lg border border-line p-6 text-center', className)}>
        <p className="text-sm text-ink-muted" data-testid={`${testId}-empty`}>
          {empty}
        </p>
        {emptyHint ? <div className="mt-2 text-sm text-ink-muted">{emptyHint}</div> : null}
      </div>
    )
  }

  const cellPadding = density === 'compact' ? 'py-1.5 pr-4' : 'py-3 pr-4'

  return (
    <div className={className} data-testid={testId} data-density={density}>
      {/* Its own scroller, so a wide table never widens the page. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead
            className={cn(
              'border-b border-line',
              // `bg-surface` is not decoration here: a transparent sticky
              // header lets rows scroll visibly underneath the labels.
              sticky && 'sticky top-0 z-10 bg-surface',
            )}
          >
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  data-column={column.key}
                  className={cn(
                    cellPadding,
                    'font-semibold text-ink',
                    column.align === 'right' && 'text-right',
                    column.width,
                    column.hideBelow && HIDE_BELOW[column.hideBelow],
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={rowKey ? rowKey(row, paging.start + index) : paging.start + index}
                className="border-b border-line/60"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    data-column={column.key}
                    className={cn(
                      cellPadding,
                      'text-ink-muted',
                      // `tabular-nums` on the right-aligned column: a column of
                      // figures that does not line up is harder to read than
                      // one that is not aligned at all.
                      column.align === 'right' && 'text-right tabular-nums',
                      column.hideBelow && HIDE_BELOW[column.hideBelow],
                    )}
                  >
                    {column.cell(row, paging.start + index)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages ? (
        <nav
          className="mt-3 flex flex-wrap items-center justify-between gap-3"
          aria-label={labels.pagination}
          data-testid={`${testId}-pager`}
        >
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            {labels.rowsPerPage}
            <select
              className="rounded-md border border-line bg-surface px-2 py-1 text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              value={paging.size}
              data-testid={`${testId}-size`}
              onChange={(event) => {
                setChosenSize(Number.parseInt(event.target.value, 10))
                // Back to the first page, always. Staying on page 9 while the
                // size grows moves the reader somewhere they did not ask to be,
                // and the row they were looking at is now on page 2.
                setRequestedPage(1)
              }}
            >
              {options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-center gap-3">
            {/*
             * Announced, because pressing Next changes content far from the
             * button and a screen-reader user otherwise hears nothing at all.
             */}
            <p className="text-sm text-ink-muted" aria-live="polite" data-testid={`${testId}-range`}>
              {labels.showing(paging.from, paging.to, paging.total)}
            </p>
            <div className="flex items-center gap-1">
              <PagerButton
                label={labels.previous}
                testId={`${testId}-previous`}
                disabled={paging.page <= 1}
                onClick={() => setRequestedPage(paging.page - 1)}
              />
              <span className="px-1 text-sm text-ink-muted" data-testid={`${testId}-page`}>
                {labels.page(paging.page, paging.pages)}
              </span>
              <PagerButton
                label={labels.next}
                testId={`${testId}-next`}
                disabled={paging.page >= paging.pages}
                onClick={() => setRequestedPage(paging.page + 1)}
              />
            </div>
          </div>
        </nav>
      ) : null}
    </div>
  )
}

/**
 * One pager control.
 *
 * `disabled` rather than hidden: a control that disappears at the ends moves
 * the other one under the pointer, and somebody clicking Next quickly then
 * presses Previous by accident. Disabled keeps the layout still and is what a
 * screen reader announces as unavailable.
 */
function PagerButton({
  label,
  testId,
  disabled,
  onClick,
}: {
  label: string
  testId: string
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="rounded-md border border-line px-2 py-1 text-sm text-ink disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {label}
    </button>
  )
}
