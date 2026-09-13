import { Button } from '../primitives/button'
import { Card } from '../primitives/card'
import type { AIActionItem } from './types'

/**
 * An action the assistant proposed, waiting for a person.
 *
 * Says what would run and with what, in the words the API recorded, and
 * offers the two decisions to somebody who may make them. For somebody who
 * may not, the buttons are absent and a sentence says who can -- a disabled
 * approve button would invite a click that the API refuses anyway, and the
 * refusal is the boundary, not this card.
 *
 * The operation is named in words rather than a colour: "Deletes something"
 * is what the person is agreeing to, and it has to survive a screen reader.
 */
export function AIActionApproval({
  action,
  labels,
  canDecide,
  busy,
  onApprove,
  onReject,
}: {
  action: AIActionItem
  labels: {
    title: string
    hint: string
    cannotDecide: string
    approve: string
    reject: string
    deciding: string
    operation: Record<AIActionItem['operation'], string>
  }
  canDecide: boolean
  busy: boolean
  onApprove: (actionId: string) => void
  onReject: (actionId: string) => void
}) {
  const input = JSON.stringify(action.input, null, 2)
  return (
    <Card
      as="article"
      className="border-brand/40 p-4 sm:p-4"
      aria-labelledby={`action-${action.id}-title`}
      data-testid="assistant-approval"
    >
      <h3 id={`action-${action.id}-title`} className="font-display text-sm font-bold text-ink">
        {labels.title}
      </h3>
      <p className="mt-1 text-xs leading-5 text-ink-muted">{labels.hint}</p>
      <dl className="mt-3 space-y-1 text-sm">
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-ink-muted">Tool</dt>
          <dd className="font-mono text-ink">{action.toolId}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-ink-muted">Effect</dt>
          <dd className="text-ink">{labels.operation[action.operation]}</dd>
        </div>
      </dl>
      <pre className="mt-3 max-h-40 overflow-auto rounded-brand bg-surface-muted p-2 font-mono text-xs text-ink">
        {input}
      </pre>
      {canDecide ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            type="button"
            loading={busy}
            onClick={() => onApprove(action.id)}
            data-testid="assistant-approve"
          >
            {busy ? labels.deciding : labels.approve}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => onReject(action.id)}
            data-testid="assistant-reject"
          >
            {labels.reject}
          </Button>
        </div>
      ) : (
        <p className="mt-4 text-sm text-ink-muted">{labels.cannotDecide}</p>
      )}
    </Card>
  )
}
