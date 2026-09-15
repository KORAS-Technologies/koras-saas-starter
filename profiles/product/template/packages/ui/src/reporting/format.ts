import type { ValueFormat } from './types'

/**
 * A number with a unit, as a person reads it.
 *
 * The API answers raw values -- bytes, millionths of a dollar, milliseconds
 * -- and says which format each is. This is the one place they become text,
 * so a card, a table cell and a chart axis agree about what 1536 means. No
 * calculation happens here; a value is scaled to its display unit and
 * nothing else.
 */
export function formatValue(value: number | null, format: ValueFormat, locale: string): string {
  if (value === null || Number.isNaN(value)) return '—'
  switch (format) {
    case 'integer':
      return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)
    case 'decimal':
      return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
    case 'percent':
      return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value) + ' %'
    case 'bytes':
      return formatBytes(value, locale)
    case 'money':
      // Micros: millionths of a US dollar, the unit the usage rows carry.
      return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: value / 1_000_000 < 1 ? 4 : 2,
      }).format(value / 1_000_000)
    case 'duration':
      return formatDuration(value, locale)
    default:
      return String(value)
  }
}

export function formatBytes(bytes: number, locale: string): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = unit === 0 ? 0 : value < 10 ? 1 : 0
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value)} ${units[unit]}`
}

/** Milliseconds as a person reads them: 812 ms, 1.4 s, 2.5 min. */
export function formatDuration(milliseconds: number, locale: string): string {
  const number = (n: number, digits: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(n)
  if (milliseconds < 1000) return `${number(milliseconds, 0)} ms`
  if (milliseconds < 60_000) return `${number(milliseconds / 1000, 1)} s`
  return `${number(milliseconds / 60_000, 1)} min`
}

/** A bucket's first day as a short date, for an axis or a table. */
export function formatBucket(iso: string, locale: string): string {
  const parsed = new Date(iso + (iso.length === 10 ? 'T00:00:00Z' : ''))
  if (Number.isNaN(parsed.getTime())) return iso
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(
    parsed,
  )
}

/** The change from the previous period, as a signed percentage or null. */
export function trend(value: number | null, previous: number | null): number | null {
  if (value === null || previous === null) return null
  if (previous === 0) return value === 0 ? 0 : null
  return Math.round(((value - previous) / previous) * 1000) / 10
}
