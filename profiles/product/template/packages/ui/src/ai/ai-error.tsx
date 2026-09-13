import { Button } from '../primitives/button'

/**
 * What went wrong, and a way onward.
 *
 * An alert, so it is announced when it appears. The sentence is the page's,
 * translated from the API's code -- never the API's own detail, and never a
 * provider's. A retry is offered where one makes sense.
 */
export function AIError({
  message,
  retryLabel,
  onRetry,
}: {
  message: string
  retryLabel?: string
  onRetry?: () => void
}) {
  return (
    <div
      role="alert"
      className="mx-4 my-2 rounded-brand border border-danger bg-surface px-4 py-3 text-sm text-ink"
      data-testid="assistant-error"
    >
      <p>{message}</p>
      {onRetry !== undefined && retryLabel !== undefined && (
        <Button type="button" variant="secondary" className="mt-3" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}
