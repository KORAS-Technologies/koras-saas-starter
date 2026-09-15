import { cn } from '../lib/cn'
import { formatBucket, formatValue } from './format'
import type { ReportingLabels, SeriesData } from './types'

/**
 * A line or a bar, drawn as inline SVG, with the same numbers as a table.
 *
 * No charting library, for the reasons the icon set gives: nothing added to
 * every generated product, nothing fetched at runtime, a drawing that
 * inherits the brand colour through `currentColor`, and accessibility that
 * is this file's to guarantee rather than a dependency's to promise. The
 * set is deliberately small -- a line over time, bars over categories --
 * and a report that needs more wants a table, which every chart carries
 * beneath it.
 *
 * Server-rendered: no `'use client'`, no state, no measurement. The SVG is
 * a viewBox scaled by CSS, so it is responsive without a resize observer.
 */
const WIDTH = 640
const HEIGHT = 240
const PAD = { top: 12, right: 12, bottom: 28, left: 52 }

export function ReportChart({
  series,
  kind,
  locale,
  labels,
  title,
  testId,
}: {
  series: SeriesData[]
  kind: 'line' | 'bar'
  locale: string
  labels: ReportingLabels
  /** What the chart shows, for its accessible name and its caption. */
  title: string
  testId?: string
}) {
  const drawn = series.filter((s) => s.points.length > 0).slice(0, 3)
  if (drawn.length === 0) {
    return (
      <p className="text-sm text-ink-muted" data-testid={testId}>
        {labels.chart.noData}
      </p>
    )
  }
  const first = drawn[0]!
  const format = first.format
  const values = drawn.flatMap((s) => s.points.map((p) => p.y ?? 0))
  const max = Math.max(1, ...values)
  const innerWidth = WIDTH - PAD.left - PAD.right
  const innerHeight = HEIGHT - PAD.top - PAD.bottom
  const y = (v: number) => PAD.top + innerHeight - (v / max) * innerHeight
  const ticks = [0, max / 2, max]
  const categories = first.points.map((p) => p.x)
  const label = (x: string) => (kind === 'line' ? formatBucket(x, locale) : x)

  return (
    <figure className="min-w-0" data-testid={testId}>
      <figcaption className="text-sm font-semibold text-ink">{title}</figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${title}: ${summary(drawn, format, locale)}`}
        className="mt-2 h-auto w-full max-w-full text-ink-muted"
        focusable="false"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="currentColor"
              strokeOpacity={0.2}
            />
            <text
              x={PAD.left - 8}
              y={y(tick) + 4}
              textAnchor="end"
              fontSize="11"
              fill="currentColor"
            >
              {formatValue(tick, format, locale)}
            </text>
          </g>
        ))}
        {kind === 'line'
          ? drawn.map((s, index) => (
              <polyline
                key={s.key}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                className={SERIES_TONES[index] ?? SERIES_TONES[0]}
                points={s.points
                  .map((p, i) => {
                    const x =
                      PAD.left + (s.points.length === 1 ? innerWidth / 2 : (i / (s.points.length - 1)) * innerWidth)
                    return `${x},${y(p.y ?? 0)}`
                  })
                  .join(' ')}
              />
            ))
          : first.points.map((p, i) => {
              const slot = innerWidth / first.points.length
              const width = Math.max(4, slot * 0.6)
              const x = PAD.left + i * slot + (slot - width) / 2
              const top = y(p.y ?? 0)
              return (
                <rect
                  key={p.x}
                  x={x}
                  y={top}
                  width={width}
                  height={Math.max(0, PAD.top + innerHeight - top)}
                  rx={2}
                  fill="currentColor"
                  className={SERIES_TONES[0]}
                />
              )
            })}
        {axisLabels(categories).map(({ index, text }) => {
          const x =
            kind === 'line'
              ? PAD.left +
                (categories.length === 1 ? innerWidth / 2 : (index / (categories.length - 1)) * innerWidth)
              : PAD.left + (index + 0.5) * (innerWidth / categories.length)
          return (
            <text
              key={index}
              x={x}
              y={HEIGHT - 8}
              textAnchor="middle"
              fontSize="11"
              fill="currentColor"
            >
              {truncate(label(text))}
            </text>
          )
        })}
      </svg>
      {drawn.length > 1 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
          {drawn.map((s, index) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn('inline-block h-2 w-2 rounded-full bg-current', SERIES_TONES[index])}
              />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      {/* The same numbers as a table: the equivalent a screen reader, a
          spreadsheet and a sceptic all prefer. Closed by default so the
          figure stays the figure. */}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-muted hover:text-ink">{labels.chart.asTable}</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="py-1.5 pr-4 font-semibold text-ink">
                  {labels.chart.period}
                </th>
                {drawn.map((s) => (
                  <th key={s.key} scope="col" className="py-1.5 pr-4 text-right font-semibold text-ink">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((category, i) => (
                <tr key={category} className="border-b border-line/60">
                  <th scope="row" className="py-1.5 pr-4 font-medium text-ink-muted">
                    {label(category)}
                  </th>
                  {drawn.map((s) => (
                    <td key={s.key} className="py-1.5 pr-4 text-right tabular-nums text-ink">
                      {formatValue(s.points[i]?.y ?? null, s.format, locale)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}

const SERIES_TONES = ['text-brand', 'text-brand-accent', 'text-ink']

function summary(series: SeriesData[], format: string, locale: string): string {
  return series
    .map((s) => {
      const total = s.points.reduce((sum, p) => sum + (p.y ?? 0), 0)
      const last = s.points[s.points.length - 1]
      const lastText = last ? formatValue(last.y, s.format, locale) : '—'
      return `${s.label}, ${s.points.length} points, total ${formatValue(total, s.format, locale)}, latest ${lastText}`
    })
    .join('; ')
}

/** Up to five labels along the axis: first, last, and evenly between. */
function axisLabels(categories: string[]): { index: number; text: string }[] {
  if (categories.length === 0) return []
  const wanted = Math.min(5, categories.length)
  const picked = new Set<number>()
  for (let i = 0; i < wanted; i += 1) {
    picked.add(Math.round((i / Math.max(1, wanted - 1)) * (categories.length - 1)))
  }
  return [...picked].sort((a, b) => a - b).map((index) => ({ index, text: categories[index] ?? '' }))
}

function truncate(text: string): string {
  return text.length > 14 ? `${text.slice(0, 13)}…` : text
}
