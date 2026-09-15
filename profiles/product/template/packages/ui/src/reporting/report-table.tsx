import { cn } from '../lib/cn'
import { formatValue } from './format'
import type { ReportingLabels, TableData } from './types'

/**
 * A report's rows.
 *
 * A real table: a caption for the reader who arrives by heading, `scope`
 * on every header, numbers right-aligned and tabular, and the whole thing
 * inside its own horizontal scroller so a wide report never widens the
 * page. Empty is a sentence, not an empty grid, and a bounded result says
 * it was bounded.
 */
export function ReportTable({
  table,
  caption,
  locale,
  labels,
  testId,
}: {
  table: TableData
  caption: string
  locale: string
  labels: ReportingLabels
  testId?: string
}) {
  if (table.rows.length === 0) {
    return (
      <p className="text-sm text-ink-muted" data-testid={testId}>
        {labels.table.empty}
      </p>
    )
  }
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line">
            {table.columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  'py-2 pr-4 font-semibold text-ink',
                  column.align === 'right' && 'text-right',
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index} className="border-b border-line/60">
              {table.columns.map((column) => {
                const cell = row[column.key] ?? null
                const text =
                  typeof cell === 'number' && column.format !== null
                    ? formatValue(cell, column.format, locale)
                    : cell === null
                      ? '—'
                      : String(cell)
                return (
                  <td
                    key={column.key}
                    className={cn(
                      'py-2 pr-4 text-ink-muted',
                      column.align === 'right' && 'text-right tabular-nums',
                    )}
                  >
                    {text}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {table.truncated && <p className="mt-2 text-xs text-ink-muted">{labels.table.truncated}</p>}
    </div>
  )
}
