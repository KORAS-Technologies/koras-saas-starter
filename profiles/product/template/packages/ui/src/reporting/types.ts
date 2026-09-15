/**
 * What the reporting components render: the API's answer, as plain data.
 *
 * Declared here rather than imported from the API client so this package
 * stays free of it, the way the AI components are. The shapes are the
 * reports router's response models; `packages/api-client` declares the same
 * fields and a page hands one to the other.
 */

export type ValueUnit = 'count' | 'bytes' | 'micros' | 'milliseconds' | 'seconds' | 'percent'
export type ValueFormat = 'integer' | 'decimal' | 'bytes' | 'money' | 'duration' | 'percent'
export type ValueKind = 'actual' | 'estimated' | 'derived' | 'unavailable'
export type VisualizationKind = 'kpi' | 'line' | 'bar' | 'table'
export type ReportVisibility = 'available' | 'locked' | 'hidden'

export interface MetricValueData {
  key: string
  label: string
  value: number | null
  unit: ValueUnit
  format: ValueFormat
  kind: ValueKind
  limit: number | null
  previous: number | null
  note: string | null
}

export interface SeriesPointData {
  x: string
  y: number | null
}

export interface SeriesData {
  key: string
  label: string
  unit: ValueUnit
  format: ValueFormat
  points: SeriesPointData[]
  kind: ValueKind
}

export interface TableColumnData {
  key: string
  label: string
  format: ValueFormat | null
  align: 'left' | 'right'
}

export type CellData = string | number | null

export interface TableData {
  columns: TableColumnData[]
  rows: Record<string, CellData>[]
  truncated: boolean
}

export interface RangeData {
  start: string
  end: string
  bucket: 'day' | 'week' | 'month'
}

export interface ReportResultData {
  key: string
  generated_at: string
  range: RangeData | null
  metrics: MetricValueData[]
  series: SeriesData[]
  table: TableData | null
  notes: string[]
  visualization: VisualizationKind
  resolved: boolean
}

export interface ReportSummaryData {
  key: string
  name: string
  description: string
  category: string
  visibility: ReportVisibility
  entitlement: string | null
  default_visualization: VisualizationKind
  sensitive: boolean
  order: number
}

export interface FilterViewData {
  key: string
  kind: 'date_range' | 'choice' | 'integer'
  label: string
  options: string[]
  default: string | number | null
  minimum: number | null
  maximum: number | null
}

export interface ReportViewData extends ReportSummaryData {
  metrics: string[]
  dimensions: string[]
  filters: FilterViewData[]
  visualizations: VisualizationKind[]
  export_formats: string[]
  can_export: boolean
  can_schedule: boolean
  cache_seconds: number
  status: string
  version: number
}

/** Every string the reporting components render, already translated. */
export interface ReportingLabels {
  /** `{used}` and `{limit}` */
  of: string
  previousPeriod: string
  up: string
  down: string
  unchanged: string
  kinds: { estimated: string; derived: string; unavailable: string }
  chart: { asTable: string; noData: string; value: string; period: string }
  table: { empty: string; truncated: string }
  filters: { period: string; from: string; to: string; apply: string }
  export: {
    download: string
    notAllowed: string
    background: string
    queued: string
    formats: Record<string, string>
  }
  schedule: {
    heading: string
    intro: string
    cadence: string
    cadences: Record<string, string>
    format: string
    recipients: string
    recipientsHint: string
    create: string
    remove: string
    empty: string
    next: string
    notIncluded: string
  }
  exports: {
    heading: string
    intro: string
    empty: string
    download: string
    pending: string
    failed: string
    retention: string
  }
  list: { heading: string; locked: string; categories: Record<string, string> }
  states: { loading: string; retry: string }
}
