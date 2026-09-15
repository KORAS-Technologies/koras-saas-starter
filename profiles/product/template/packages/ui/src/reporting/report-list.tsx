import Link from 'next/link'
import { cn } from '../lib/cn'
import type { ReportSummaryData, ReportingLabels } from './types'

/**
 * Every report this caller may see, grouped by category, with the current
 * one marked.
 *
 * The same treatment the sidebar gives its modules: an available report is
 * a link with `aria-current` when it is the page; a locked one is a
 * disabled button whose accessible name carries the reason, because a
 * customer could buy it and should know it exists. Hidden reports are not
 * in the list at all -- the API already left them out.
 */
export function ReportList({
  reports,
  current,
  hrefFor,
  labels,
}: {
  reports: ReportSummaryData[]
  current: string
  hrefFor: (key: string) => string
  labels: ReportingLabels
}) {
  const categories = [...new Set(reports.map((r) => r.category))]
  return (
    <nav aria-label={labels.list.heading} className="text-sm" data-testid="report-list">
      {categories.map((category) => (
        <div key={category} className="mb-4">
          <p className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            {labels.list.categories[category] ?? category}
          </p>
          <ul className="space-y-0.5">
            {reports
              .filter((r) => r.category === category)
              .map((report) =>
                report.visibility === 'locked' ? (
                  <li key={report.key}>
                    <button
                      type="button"
                      disabled
                      className="flex min-h-10 w-full cursor-not-allowed items-center rounded-brand px-3 text-left text-ink-muted opacity-60"
                    >
                      <span aria-hidden="true">{report.name}</span>
                      <span className="sr-only">
                        {report.name}. {labels.list.locked}
                      </span>
                    </button>
                  </li>
                ) : (
                  <li key={report.key}>
                    <Link
                      href={hrefFor(report.key)}
                      aria-current={report.key === current ? 'page' : undefined}
                      className={cn(
                        'flex min-h-10 items-center rounded-brand px-3 font-medium transition-colors',
                        report.key === current
                          ? 'bg-brand/10 text-brand'
                          : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                      )}
                    >
                      {report.name}
                    </Link>
                  </li>
                ),
              )}
          </ul>
        </div>
      ))}
    </nav>
  )
}
