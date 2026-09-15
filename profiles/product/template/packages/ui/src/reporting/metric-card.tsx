import type { ReactNode } from 'react'
import { cn } from '../lib/cn'
import { formatValue, trend } from './format'
import type { MetricValueData, ReportingLabels } from './types'

/**
 * One number, with what it is measured against.
 *
 * A metric on a customer's dashboard is a starting point for a question,
 * not a headline, so the card says three things beside the figure: how
 * much of the plan's ceiling it is, where a ceiling exists; how it moved
 * against the previous period, where a comparison exists; and what kind of
 * number it is, whenever it is not simply a count of the customer's own
 * rows. A figure the system could not obtain is a dash, never a zero.
 */
export function MetricCard({
  metric,
  locale,
  labels,
  testId,
}: {
  metric: MetricValueData
  locale: string
  labels: ReportingLabels
  testId?: string
}) {
  const value = formatValue(metric.value, metric.format, locale)
  const limit = metric.limit === null ? null : formatValue(metric.limit, metric.format, locale)
  const share =
    metric.limit !== null && metric.limit > 0 && metric.value !== null
      ? Math.min(100, Math.round((metric.value / metric.limit) * 100))
      : null
  const change = trend(metric.value, metric.previous)
  const kind = metric.kind === 'actual' ? null : labels.kinds[metric.kind]

  return (
    <article
      className="rounded-brand border border-line bg-surface p-4 shadow-card sm:p-5"
      data-testid={testId ?? `metric-${metric.key}`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{metric.label}</p>
      <p className="mt-2 font-display text-2xl font-bold tabular-nums text-ink">
        {value}
        {limit !== null && (
          <span className="ml-1 text-sm font-medium text-ink-muted">
            {fill(labels.of, { used: '', limit }).trim()}
          </span>
        )}
      </p>
      {share !== null && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={share}
          aria-label={`${metric.label}: ${fill(labels.of, { used: value, limit: limit ?? '' })}`}
          className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
        >
          <div
            className={cn('h-full rounded-full', share >= 90 ? 'bg-red-600' : 'bg-brand')}
            style={{ width: `${share}%` }}
          />
        </div>
      )}
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
        {change !== null && <Trend change={change} labels={labels} />}
        {kind !== null && (
          <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium">
            {kind}
          </span>
        )}
        {metric.note !== null && <span>{metric.note}</span>}
      </p>
    </article>
  )
}

function Trend({ change, labels }: { change: number; labels: ReportingLabels }): ReactNode {
  const direction = change > 0 ? labels.up : change < 0 ? labels.down : labels.unchanged
  const tone = change > 0 ? 'text-emerald-700' : change < 0 ? 'text-red-700' : 'text-ink-muted'
  return (
    <span className={cn('font-medium tabular-nums', tone)}>
      <span aria-hidden="true">{change > 0 ? '▲' : change < 0 ? '▼' : '•'} </span>
      <span className="sr-only">{direction} </span>
      {Math.abs(change)} % {labels.previousPeriod}
    </span>
  )
}

/** A grid that holds two cards at phone width and four on a desktop. */
export function MetricGrid({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" data-testid={testId}>
      {children}
    </div>
  )
}

export function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? '')
}
