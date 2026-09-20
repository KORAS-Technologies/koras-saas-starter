'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'
import { useSettingValue } from '../settings/provider'
import {
  applyArrangement,
  clampWidth,
  readArrangement,
  writeArrangement,
  type Arrangement,
} from './columns'
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
 * **What it honours, as of 2026-09-19.** `grid.pageSize`,
 * `grid.pageSizeOptions`, `grid.paginationEnabled`, `grid.stickyHeader`,
 * `grid.rowDensity`, `grid.allowColumnResize`, `grid.allowColumnReorder` and
 * `grid.rememberColumns` — eight of the ten. The two left are `rememberFilters`
 * and `rememberSort`, and they are left because this table has no filter and no
 * sort: they describe persistence of state it does not own. A filter and a sort
 * belong to the surface above it, which is where that state lives in the
 * Control Plane's toolbar too. Declaring them costs nothing and reserves the
 * vocabulary; reading them and doing nothing would be worse, because a setting
 * that visibly does nothing teaches people the whole framework is decorative.
 *
 * **Resizing and reordering need a `tableId` to be remembered.** Without one
 * they still work and last as long as the page, because two tables on a screen
 * with no identity between them would otherwise share one arrangement and each
 * would move when the other was dragged.
 *
 * ## Paging on the client, or on the server
 *
 * By default the table takes the whole array and slices it, which is right for
 * a list that fits in a response and wrong for one that does not.
 *
 * Pass `total` and the table stops slicing: `data` is *this page*, `total` is
 * how many there are, `page` is which one, and `onPageChange` is how the
 * surface is told to fetch another. Nothing else changes — the pager, the size
 * control, the range and the announcements are the same, which is the point of
 * putting the seam here rather than in each surface.
 *
 * ```tsx
 * <KorasDataTable
 *   data={page.rows} total={page.total} page={page.number}
 *   onPageChange={(next) => void load(next)} loading={pending}
 *   columns={columns} caption="Audit" labels={labels} />
 * ```
 *
 * `loading` dims the rows and disables the pager rather than replacing the
 * table with a spinner: a table that vanishes while the next page loads moves
 * everything under the pointer and loses the reader's place.
 *
 * **Paging state stays the component's, not the URL's.** A table that wrote its
 * page into the query string would fight the toolbar above it for the same
 * parameter, and two tables on one screen would fight each other. A surface
 * that wants a shareable page owns the state and passes `page` down, which is
 * the same seam server paging uses.
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
  /** Neither resized nor moved, whatever the settings say. For a column whose
   * position carries meaning — a row selector, an actions column at the end —
   * where letting somebody drag it produces a table that reads as broken. */
  fixed?: boolean
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
  total,
  page,
  onPageChange,
  loading = false,
  tableId,
  allowColumnResize,
  allowColumnReorder,
  rememberColumns,
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
  /**
   * How many rows there are in total, when `data` is one page of them.
   *
   * Its presence is what switches the table from slicing to trusting: given a
   * `total`, `data` is rendered as-is and the pager reports against `total`.
   */
  total?: number
  /** Which page `data` is, 1-based. Required in effect when `total` is given. */
  page?: number
  /** Told when somebody asks for another page. Without it the pager is inert. */
  onPageChange?: (page: number, size: number) => void
  /** Dims the rows and disables the pager. The table stays where it is. */
  loading?: boolean
  /**
   * What makes this table itself, for remembering an arrangement.
   *
   * Without it resizing and reordering still work and last as long as the page.
   * Two tables on a screen with no identity between them would otherwise share
   * one arrangement and each would move when the other was dragged.
   */
  tableId?: string
  /** Overrides `grid.allowColumnResize`. */
  allowColumnResize?: boolean
  /** Overrides `grid.allowColumnReorder`. */
  allowColumnReorder?: boolean
  /** Overrides `grid.rememberColumns`. */
  rememberColumns?: boolean
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

  // Each fallback is the catalogue's own default, so a table rendered outside
  // the settings provider behaves as a configured one does. `allowColumnReorder`
  // is off by default there and so is off here: moving a column is a new
  // interaction, and a product turns it on deliberately.
  const settingResize = useSettingValue('grid.allowColumnResize', true)
  const settingReorder = useSettingValue('grid.allowColumnReorder', false)
  const settingRemember = useSettingValue('grid.rememberColumns', true)

  const pages = paginationEnabled ?? settingPaging
  const sticky = stickyHeader ?? settingSticky
  const density = rowDensity ?? (settingDensity === 'compact' ? 'compact' : 'comfortable')
  const canResize = allowColumnResize ?? settingResize
  const canReorder = allowColumnReorder ?? settingReorder
  const remembers = (rememberColumns ?? settingRemember) && Boolean(tableId)

  // Server paging is a mode, and `total` is what selects it. Named rather than
  // tested inline, because "is this table slicing?" is asked in four places and
  // three of them would eventually disagree.
  const served = total !== undefined

  // Clamped whether it arrived from a prop or a setting: the API checked the
  // setting against the definition, and nothing checked the prop.
  const resolvedSize = clampSize(pageSize ?? settingSize)

  // The size a person picked for this table, which outlives neither the page
  // nor the navigation. Changing it for good is `/dashboard/preferences`;
  // changing it here is for looking at this list right now.
  const [chosenSize, setChosenSize] = useState<number | null>(null)
  const [requestedPage, setRequestedPage] = useState(1)

  const size = pages ? (chosenSize ?? resolvedSize) : 0
  // On the server the caller owns the page number, so the component's own is
  // ignored rather than kept in step — two sources for one value is how a
  // pager ends up one click behind what is on screen.
  const paging = paginate(served ? total : data.length, served ? (page ?? 1) : requestedPage, size)

  const goTo = useCallback(
    (next: number) => {
      if (served) onPageChange?.(next, size)
      else setRequestedPage(next)
    },
    [onPageChange, served, size],
  )
  // Keyed on the size rather than on the `paging` object, which is rebuilt
  // every render and would make the memo do nothing but allocate.
  const options = useMemo(
    () => sizeOptions(settingOptions, paging.size),
    [settingOptions, paging.size],
  )

  // Sliced only when this table is the one doing the paging. Given a `total`,
  // `data` is already the page and slicing it again would show the first
  // fifty rows of every page.
  const rows = pages && !served ? data.slice(paging.start, paging.end) : data

  // Restored after mount, never during render: the server has no storage, so
  // reading it while rendering produces markup the client does not agree with
  // and React logs a hydration failure. The first client pass matches the
  // server's declared order and the arrangement lands immediately after.
  const [arrangement, setArrangement] = useState<Arrangement | null>(null)
  useEffect(() => {
    if (!remembers || !tableId) return
    const stored = readArrangement(tableId)
    latest.current = stored
    setArrangement(stored)
  }, [remembers, tableId])

  // The same value as the state, kept where an event handler can read it
  // without being a state updater. `setArrangement` used to carry the write
  // inside its updater, which React may call more than once -- Strict Mode
  // does so deliberately -- and an updater is required to be pure. The write
  // is idempotent so nothing broke; the pattern breaks the next time something
  // in one is not. TBL-03.
  const latest = useRef<Arrangement | null>(null)

  const remember = useCallback(
    (next: Arrangement | null) => {
      latest.current = next
      setArrangement(next)
      if (remembers && tableId) writeArrangement(tableId, next)
    },
    [remembers, tableId],
  )

  // Fixed columns keep their declared position: an arrangement is a hint about
  // the rest, and a table whose actions column has been dragged into the middle
  // reads as broken rather than as arranged.
  const arranged = useMemo(() => {
    const movable = columns.filter((column) => !column.fixed)
    const ordered = applyArrangement(movable, arrangement)
    const queue = [...ordered]
    return columns.map((column) => (column.fixed ? column : (queue.shift() ?? column)))
  }, [columns, arrangement])

  const widths = arrangement?.widths ?? {}
  const drag = useRef<{ key: string; startX: number; startWidth: number } | null>(null)

  const onResizeStart = useCallback(
    (key: string, event: React.PointerEvent<HTMLElement>) => {
      const cell = event.currentTarget.closest('th')
      if (!cell) return
      event.preventDefault()
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { key, startX: event.clientX, startWidth: cell.getBoundingClientRect().width }
    },
    [],
  )

  const onResizeMove = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const active = drag.current
      if (!active) return
      const width = clampWidth(active.startWidth + (event.clientX - active.startX))
      if (width === null) return
      const next = {
        ...latest.current,
        widths: { ...latest.current?.widths, [active.key]: width },
      }
      latest.current = next
      setArrangement(next)
    },
    [],
  )

  const onResizeEnd = useCallback(() => {
    if (!drag.current) return
    drag.current = null
    // Written once, at the end of the gesture, rather than on every pointer
    // move: a drag across a wide table is hundreds of events and each one
    // would be a synchronous write. From the ref rather than from a state
    // updater, which is TBL-03.
    if (remembers && tableId) writeArrangement(tableId, latest.current)
  }, [remembers, tableId])

  const moveColumn = useCallback(
    (key: string, direction: -1 | 1) => {
      const order = arranged.filter((column) => !column.fixed).map((column) => column.key)
      const at = order.indexOf(key)
      const to = at + direction
      if (at < 0 || to < 0 || to >= order.length) return
      const next = [...order]
      next[at] = order[to]!
      next[to] = key
      remember({ order: next, widths: arrangement?.widths })
    },
    [arranged, arrangement, remember],
  )

  // **Not while loading.** For a client-paged table an empty array means an
  // empty list and this sentence is right. For a served one the first render
  // has no rows because they have not arrived, so every server-paged table
  // would open by saying there is nothing there and then contradicting itself
  // — which is the worst sentence on the page to show wrongly, and the same
  // argument the Restore page applies to an empty backup catalogue. TBL-02.
  if (data.length === 0 && !loading) {
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

  // **A width is only a width under fixed layout.** With `table-layout: auto`
  // — the default, and what this used all of 2026-09-19 — a `width` on a cell
  // is a hint the browser satisfies *after* content, so dragging a column
  // wider worked and dragging it narrower did nothing, on exactly the columns
  // anybody would want to narrow. TBL-01.
  //
  // Automatic layout stays the default, because it is the better one for a
  // table nobody has arranged: it sizes columns to what is in them. The switch
  // happens the moment somebody sets a width, and only then.
  const arrangedWidths = Object.keys(widths).length > 0

  return (
    <div className={className} data-testid={testId} data-density={density}>
      {/* Its own scroller, so a wide table never widens the page. */}
      <div className="overflow-x-auto">
        <table
          className={cn(
            'w-full border-collapse text-left text-sm',
            arrangedWidths && 'table-fixed',
          )}
        >
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
              {arranged.map((column, index) => (
                <th
                  key={column.key}
                  scope="col"
                  data-column={column.key}
                  // A stored width wins over the declared class, which is why
                  // the class stays: without an arrangement the column is
                  // exactly what the developer asked for.
                  style={widths[column.key] ? { width: widths[column.key] } : undefined}
                  className={cn(
                    cellPadding,
                    'group relative font-semibold text-ink',
                    column.align === 'right' && 'text-right',
                    !widths[column.key] && column.width,
                    // Clipped under fixed layout: content that no longer fits
                    // must not be what decides the width, or narrowing is
                    // undone by the first long cell.
                    arrangedWidths && 'truncate',
                    column.hideBelow && HIDE_BELOW[column.hideBelow],
                  )}
                >
                  <span className="inline-flex items-center gap-1">
                    {column.header}
                    {canReorder && !column.fixed ? (
                      <MoveButtons
                        labels={labels}
                        header={column.header}
                        testId={`${testId}-move-${column.key}`}
                        canMoveLeft={index > 0 && !arranged[index - 1]?.fixed}
                        canMoveRight={
                          index < arranged.length - 1 && !arranged[index + 1]?.fixed
                        }
                        onMove={(direction) => moveColumn(column.key, direction)}
                      />
                    ) : null}
                  </span>
                  {canResize && !column.fixed ? (
                    /*
                     * A pointer target, not a control. Resizing is a refinement
                     * of something already legible, so it is deliberately not
                     * in the tab order and carries `aria-hidden`: a keyboard
                     * user gets the reorder buttons, which change what can be
                     * read, and is not made to tab through a handle per column
                     * that changes only how wide it is.
                     */
                    <span
                      aria-hidden="true"
                      data-testid={`${testId}-resize-${column.key}`}
                      onPointerDown={(event) => onResizeStart(column.key, event)}
                      onPointerMove={onResizeMove}
                      onPointerUp={onResizeEnd}
                      onPointerCancel={onResizeEnd}
                      className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none bg-transparent opacity-0 transition-opacity group-hover:bg-line group-hover:opacity-100"
                    />
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody
            // Dimmed rather than replaced. A table that vanishes while the next
            // page loads moves everything under the pointer and loses the
            // reader's place; `aria-busy` is what says so to a screen reader.
            aria-busy={loading || undefined}
            className={cn(loading && 'opacity-60 transition-opacity')}
          >
            {rows.map((row, index) => (
              <tr
                key={rowKey ? rowKey(row, paging.start + index) : paging.start + index}
                className="border-b border-line/60"
              >
                {arranged.map((column) => (
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
                      arrangedWidths && 'truncate',
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
              disabled={loading}
              data-testid={`${testId}-size`}
              onChange={(event) => {
                const next = clampSize(Number.parseInt(event.target.value, 10))
                setChosenSize(next)
                // Back to the first page, always. Staying on page 9 while the
                // size grows moves the reader somewhere they did not ask to be,
                // and the row they were looking at is now on page 2.
                setRequestedPage(1)
                // The caller is told the size as well as the page, because on
                // the server a size change is a different request and it
                // cannot be inferred from the page number alone.
                if (served) onPageChange?.(1, next)
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
                disabled={loading || paging.page <= 1}
                onClick={() => goTo(paging.page - 1)}
              />
              <span className="px-1 text-sm text-ink-muted" data-testid={`${testId}-page`}>
                {labels.page(paging.page, paging.pages)}
              </span>
              <PagerButton
                label={labels.next}
                testId={`${testId}-next`}
                disabled={loading || paging.page >= paging.pages}
                onClick={() => goTo(paging.page + 1)}
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


/**
 * Move a column left or right.
 *
 * Buttons rather than drag-and-drop, and that is the accessibility decision
 * rather than a shortcut. A drag is invisible to a keyboard and awkward on a
 * touch screen; two buttons work everywhere, are announceable, and do not need
 * a live region to explain what just happened because the header order is the
 * announcement. Drag may be added on top one day; it may not replace these.
 *
 * Shown on hover and on focus. Always-visible arrows on every header turn a
 * table into a control panel, and `group-focus-within` is what keeps them
 * reachable for somebody who never hovers anything.
 */
function MoveButtons({
  labels,
  header,
  testId,
  canMoveLeft,
  canMoveRight,
  onMove,
}: {
  labels: DataTableLabels
  header: string
  testId: string
  canMoveLeft: boolean
  canMoveRight: boolean
  onMove: (direction: -1 | 1) => void
}) {
  const base =
    'rounded px-1 text-xs leading-none text-ink-muted opacity-0 transition-opacity ' +
    'group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline ' +
    'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ' +
    'disabled:cursor-not-allowed disabled:opacity-0'
  return (
    <span className="inline-flex items-center">
      <button
        type="button"
        className={base}
        data-testid={`${testId}-left`}
        disabled={!canMoveLeft}
        // The column's name is in the label, because "move left" repeated
        // across nine headers is nine identical controls to a screen reader.
        aria-label={labels.moveColumnLeft(header)}
        onClick={() => onMove(-1)}
      >
        {'\u2039'}
      </button>
      <button
        type="button"
        className={base}
        data-testid={`${testId}-right`}
        disabled={!canMoveRight}
        aria-label={labels.moveColumnRight(header)}
        onClick={() => onMove(1)}
      >
        {'\u203a'}
      </button>
    </span>
  )
}
