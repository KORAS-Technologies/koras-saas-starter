/**
 * How much of the month's allowance is spent, in one line.
 *
 * Three sentences, chosen by the page: a limit and a count, a count alone,
 * or nothing known. Already translated and filled; this only places it.
 */
export function AIUsageNotice({ text }: { text: string | null }) {
  if (text === null) return null
  return (
    <p className="px-4 pt-3 text-xs text-ink-muted" data-testid="assistant-usage">
      {text}
    </p>
  )
}
