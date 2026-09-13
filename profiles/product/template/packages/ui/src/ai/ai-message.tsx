import { cn } from '../lib/cn'
import type { AIMessageItem } from './types'

/**
 * One message, as text.
 *
 * Text and nothing else. A model's answer is rendered with `whitespace-pre-wrap`
 * so its line breaks survive, and it is never parsed as markup: an answer that
 * could carry a tag could carry a script, and the text a model returns is
 * shaped by text a customer typed. The speaker is announced for a screen
 * reader and shown for everyone else through alignment and tint.
 */
export function AIMessage({
  message,
  youLabel,
  speakerLabel,
}: {
  message: AIMessageItem
  youLabel: string
  speakerLabel: string
}) {
  const mine = message.role === 'user'
  return (
    <div className={cn('flex', mine ? 'justify-end' : 'justify-start')} data-role={message.role}>
      <div
        className={cn(
          'max-w-[85%] rounded-brand px-4 py-3 text-sm leading-6',
          mine ? 'bg-brand text-white' : 'border border-line bg-surface text-ink',
        )}
      >
        <span className="sr-only">{mine ? youLabel : speakerLabel}: </span>
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
      </div>
    </div>
  )
}
