import type { ReactNode } from 'react'
import { Button } from '../primitives/button'
import { SelectField, TextField } from '../primitives/field'
import { formatBytes } from './format'
import type { ReportingLabels } from './types'

/**
 * Scheduled delivery and background exports, as the page shows them.
 *
 * Both are plain forms posting to server actions the page supplies, so
 * no client component and no API address reaches the browser. The list
 * of what exists is rendered from what the API answered; nothing here
 * decides who may schedule, it renders a decision the page made.
 */

export interface ScheduleData {
  id: string
  cadence: string
  format: string
  recipients: string[]
  next_run_at: string
  last_run_at: string | null
  last_error: string | null
}

export interface ExportData {
  id: string
  report_key: string
  format: string
  status: string
  filename: string
  rows: number
  size_bytes: number | null
  error: string | null
  created_at: string
}

export function ScheduleForm({
  action,
  reportKey,
  formats,
  hiddenFilters,
  labels,
  error,
}: {
  /** A server action taking the form data. */
  action: (data: FormData) => void | Promise<void>
  reportKey: string
  formats: string[]
  /** The page's current non-period filters, carried into the schedule. */
  hiddenFilters: Record<string, string>
  labels: ReportingLabels
  error?: string
}) {
  return (
    <form
      action={action}
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end"
      data-testid="schedule-form"
    >
      <input type="hidden" name="report" value={reportKey} />
      {Object.entries(hiddenFilters).map(([name, value]) => (
        <input key={name} type="hidden" name={`filter:${name}`} value={value} />
      ))}
      <SelectField
        id="schedule-cadence"
        name="cadence"
        label={labels.schedule.cadence}
        defaultValue="weekly"
      >
        <option value="daily">{labels.schedule.cadences.daily}</option>
        <option value="weekly">{labels.schedule.cadences.weekly}</option>
        <option value="monthly">{labels.schedule.cadences.monthly}</option>
      </SelectField>
      <SelectField
        id="schedule-format"
        name="format"
        label={labels.schedule.format}
        defaultValue={formats[0] ?? 'csv'}
      >
        {formats.map((format) => (
          <option key={format} value={format}>
            {labels.export.formats[format] ?? format.toUpperCase()}
          </option>
        ))}
      </SelectField>
      <TextField
        id="schedule-recipients"
        name="recipients"
        label={labels.schedule.recipients}
        hint={labels.schedule.recipientsHint}
        error={error}
        type="text"
        autoComplete="off"
        required
      />
      <div>
        <Button type="submit" variant="secondary">
          {labels.schedule.create}
        </Button>
      </div>
    </form>
  )
}

export function ScheduleList({
  schedules,
  locale,
  labels,
  remove,
}: {
  schedules: ScheduleData[]
  locale: string
  labels: ReportingLabels
  /** A server action taking the form data with the schedule's id. */
  remove: (data: FormData) => void | Promise<void>
}) {
  if (schedules.length === 0) {
    return (
      <p className="text-sm text-ink-muted" data-testid="schedule-list-empty">
        {labels.schedule.empty}
      </p>
    )
  }
  return (
    <ul className="divide-y divide-line text-sm" data-testid="schedule-list">
      {schedules.map((schedule) => (
        <li key={schedule.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
          <span className="font-medium text-ink">
            {labels.schedule.cadences[schedule.cadence] ?? schedule.cadence}
            {' · '}
            {labels.export.formats[schedule.format] ?? schedule.format.toUpperCase()}
          </span>
          <span className="text-ink-muted">{schedule.recipients.join(', ')}</span>
          <span className="text-xs text-ink-muted">
            {labels.schedule.next} {formatMoment(schedule.next_run_at, locale)}
          </span>
          {schedule.last_error !== null && (
            <span className="text-xs text-red-700" role="status">
              {schedule.last_error}
            </span>
          )}
          <form action={remove} className="ml-auto">
            <input type="hidden" name="schedule" value={schedule.id} />
            <Button type="submit" variant="ghost">
              {labels.schedule.remove}
            </Button>
          </form>
        </li>
      ))}
    </ul>
  )
}

export function ExportList({
  exports,
  retentionDays,
  locale,
  labels,
  downloadHref,
}: {
  exports: ExportData[]
  retentionDays: number
  locale: string
  labels: ReportingLabels
  downloadHref: (id: string) => string
}) {
  if (exports.length === 0) {
    return (
      <p className="text-sm text-ink-muted" data-testid="export-list-empty">
        {labels.exports.empty}
      </p>
    )
  }
  return (
    <div data-testid="export-list">
      <ul className="divide-y divide-line text-sm">
        {exports.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
            <span className="font-medium text-ink">{item.filename}</span>
            <span className="text-xs text-ink-muted">{formatMoment(item.created_at, locale)}</span>
            <span className="text-xs text-ink-muted">
              {item.size_bytes !== null ? formatBytes(item.size_bytes, locale) : `${item.rows} rows`}
            </span>
            <span className="ml-auto">{statusOf(item, labels, downloadHref)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-muted">
        {fill(labels.exports.retention, { days: String(retentionDays) })}
      </p>
    </div>
  )
}

function statusOf(
  item: ExportData,
  labels: ReportingLabels,
  downloadHref: (id: string) => string,
): ReactNode {
  if (item.status === 'ready') {
    return (
      <a href={downloadHref(item.id)} className="text-brand underline-offset-2 hover:underline">
        {labels.exports.download}
      </a>
    )
  }
  if (item.status === 'failed') {
    return (
      <span className="text-xs text-red-700" role="status">
        {item.error ?? labels.exports.failed}
      </span>
    )
  }
  return <span className="text-xs text-ink-muted">{labels.exports.pending}</span>
}

/** A moment as a person reads it, in their language: date and time, no seconds. */
function formatMoment(iso: string, locale: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
    parsed,
  )
}

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? '')
}
