import { ButtonLink } from '../primitives/button'
import { Card } from '../primitives/card'
import type { ReportingLabels } from './types'

/**
 * The three states a report has before it has numbers.
 *
 * Loading is announced, not merely spun; an error is an alert with a way
 * to try again, because the backing service being absent is the ordinary
 * state of this page in a browser test and a bad afternoon in production;
 * and empty is a sentence about the range rather than a blank card.
 */
export function ReportLoadingState({ labels }: { labels: ReportingLabels }) {
  return (
    <Card className="animate-pulse" data-testid="report-loading">
      <p className="sr-only" aria-live="polite" aria-busy="true">
        {labels.states.loading}
      </p>
      <div className="h-4 w-1/3 rounded bg-surface-muted" aria-hidden="true" />
      <div className="mt-4 h-24 w-full rounded bg-surface-muted" aria-hidden="true" />
    </Card>
  )
}

export function ReportErrorState({
  message,
  retryHref,
  labels,
}: {
  message: string
  retryHref: string
  labels: ReportingLabels
}) {
  return (
    <Card className="border-red-600/40" data-testid="report-error">
      <p role="alert" className="text-sm leading-6 text-ink">
        {message}
      </p>
      <div className="mt-4">
        <ButtonLink href={retryHref} variant="secondary">
          {labels.states.retry}
        </ButtonLink>
      </div>
    </Card>
  )
}

export function ReportEmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <Card data-testid="report-empty">
      <p className="text-sm font-semibold text-ink">{title}</p>
      {hint !== undefined && <p className="mt-1 text-sm text-ink-muted">{hint}</p>}
    </Card>
  )
}
