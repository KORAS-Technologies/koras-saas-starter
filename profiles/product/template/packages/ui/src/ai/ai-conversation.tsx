import type { ReactNode } from 'react'
import { AICitations } from './ai-citations'
import { AIMessage } from './ai-message'
import { AIToolResult } from './ai-tool-result'
import type { AIConversationLabels, AIMessageItem } from './types'

/**
 * The messages, in order, or the empty state.
 *
 * A live region, so an answer arriving is announced without stealing focus
 * from the composer. Polite rather than assertive: a person mid-sentence
 * should finish it. Tool messages render folded; system messages are never
 * sent to the browser and are skipped if one ever is.
 */
export function AIConversation({
  messages,
  labels,
  footer,
}: {
  messages: AIMessageItem[]
  labels: AIConversationLabels
  /** Rendered after the last message: a pending approval, an error. */
  footer?: ReactNode
}) {
  const shown = messages.filter((m) => m.role !== 'system')
  return (
    <div
      className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
      aria-live="polite"
      aria-relevant="additions"
      data-testid="assistant-conversation"
    >
      {shown.length === 0 && footer === undefined ? (
        <div className="my-auto text-center">
          <p className="font-display text-base font-bold text-ink">{labels.empty}</p>
          <p className="mt-2 text-sm leading-6 text-ink-muted">{labels.emptyHint}</p>
        </div>
      ) : (
        shown.map((message) =>
          message.role === 'tool' ? (
            <AIToolResult
              key={message.id}
              toolName={message.toolName ?? ''}
              content={message.content}
              label={labels.toolResult.replace('{tool}', message.toolName ?? '')}
              showLabel={labels.toolResultShow}
            />
          ) : (
            <div key={message.id} className="flex flex-col gap-2">
              <AIMessage message={message} youLabel={labels.you} speakerLabel={labels.speaker} />
              {message.citations && message.citations.length > 0 ? (
                <AICitations title={labels.citations} citations={message.citations} />
              ) : null}
            </div>
          ),
        )
      )}
      {footer}
    </div>
  )
}
