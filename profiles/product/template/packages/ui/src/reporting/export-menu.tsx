import { ButtonLink } from '../primitives/button'
import type { ReportingLabels } from './types'

/**
 * The download.
 *
 * A plain anchor to the export route handler -- `ButtonLink` renders one
 * for any `/api/` href, so the router never prefetches it, which matters
 * here more than anywhere: a prefetch would be an export nobody asked for,
 * recorded in the audit table as if they had. The server decides again
 * whether this caller may export; the button only says what it already
 * knows, so a person is not offered a download the API will refuse.
 */
export function ExportMenu({
  href,
  allowed,
  labels,
}: {
  href: string
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
    <ButtonLink href={href} variant="secondary" testId="report-export">
      {labels.export.download}
    </ButtonLink>
  )
}
