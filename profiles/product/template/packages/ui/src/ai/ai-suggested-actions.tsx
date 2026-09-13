import { Button } from '../primitives/button'

/**
 * A few things to ask, for a conversation that has not started.
 *
 * Plain buttons that put a sentence into the composer's hands. Suggestions
 * are the page's to choose -- a product knows what its assistant is for --
 * and this only draws them.
 */
export function AISuggestedActions({
  title,
  suggestions,
  disabled = false,
  onPick,
}: {
  title: string
  suggestions: readonly string[]
  disabled?: boolean
  onPick: (text: string) => void
}) {
  if (suggestions.length === 0) return null
  return (
    <div className="px-4 pb-3" data-testid="assistant-suggestions">
      <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{title}</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {suggestions.map((suggestion) => (
          <li key={suggestion}>
            <Button
              type="button"
              variant="secondary"
              disabled={disabled}
              onClick={() => onPick(suggestion)}
            >
              {suggestion}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}
