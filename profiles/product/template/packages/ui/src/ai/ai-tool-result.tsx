/**
 * What a tool answered, folded away.
 *
 * A native disclosure: the summary is the tool's name and the body is the
 * result as it was recorded, in a scrolling block. Folded by default because
 * the answer that follows is what the person asked for; the result is there
 * for whoever wants to check it against the answer, which is the whole point
 * of showing it at all.
 */
export function AIToolResult({
  toolName,
  content,
  label,
  showLabel,
}: {
  toolName: string
  content: string
  /** Already translated, with `{tool}` filled: "Result from files.list". */
  label: string
  showLabel: string
}) {
  return (
    <details className="rounded-brand border border-line bg-surface-muted px-3 py-2 text-xs text-ink-muted">
      <summary className="cursor-pointer font-medium text-ink">
        {label}
        <span className="sr-only"> — {showLabel}</span>
      </summary>
      <pre
        className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono"
        data-tool={toolName}
      >
        {content}
      </pre>
    </details>
  )
}
