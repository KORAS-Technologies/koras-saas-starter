import { ButtonLink } from '../primitives/button'
import type { ReportingLabels } from './types'

/**
 * The downloads: one link per format the report offers, plus the way to
 * ask for the file in the background when it will be large.
 *
 * Plain anchors to the export route handler -- `ButtonLink` renders one
 * for any `/api/` href, so the router never prefetches it, which matters
 * here more than anywhere: a prefetch would be an export nobody asked for,
 * recorded in the audit table as if they had. The server decides again
 * whether this caller may export; the links only say what it already
 * knows, so a person is not offered a download the API will refuse.
 */
export function ExportMenu({
  hrefFor,
  formats,
  allowed,
  labels,
}: {
  /** The route handler's href for a format, with the page's filters carried. */
  hrefFor: (format: string, background: boolean) => string
  formats: string[]
  allowed: boolean
  labels: ReportingLabels
}) {
  if (!allowed) {
    return (
      <p className="text-xs text-ink-muted" data-testid="report-export-locked">
        {labels.export.notAllowed}
      </p>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="report-export">
      {formats.map((format) => (
        <ButtonLink
          key={format}
          href={hrefFor(format, false)}
          variant="secondary"
          testId={`report-export-${format}`}
        >
          {labels.export.formats[format] ?? format.toUpperCase()}
        </ButtonLink>
      ))}
      <ButtonLink
        href={hrefFor(formats[0] ?? 'csv', true)}
        variant="ghost"
        testId="report-export-background"
      >
        {labels.export.background}
      </ButtonLink>
    </div>
  )
}
