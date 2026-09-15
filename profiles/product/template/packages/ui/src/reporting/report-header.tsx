import type { ReactNode } from 'react'
import type { RangeData } from './types'

/**
 * A report's name, what it is, the period it covers, and its actions.
 *
 * The one `h1` on the page belongs here, not to the analytics landing:
 * a report is the page, and the list beside it is navigation.
 */
export function ReportHeader({
  title,
  description,
  range,
  locale,
  actions,
  notes,
}: {
  title: string
  description: string
  range: RangeData | null
  locale: string
  actions?: ReactNode
  notes?: string[]
}) {
  const period =
    range === null
      ? null
      : `${formatDay(range.start, locale)} – ${formatDay(range.end, locale)}`
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-bold text-ink">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-muted">{description}</p>
        {period !== null && (
          <p className="mt-1 text-xs text-ink-muted" data-testid="report-period">
            {period}
          </p>
        )}
        {notes !== undefined && notes.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-ink-muted" data-testid="report-notes">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>
      {actions !== undefined && <div className="shrink-0">{actions}</div>}
    </header>
  )
}

function formatDay(iso: string, locale: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return iso
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(parsed)
}
