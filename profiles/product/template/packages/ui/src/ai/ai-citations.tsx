import type { AICitationItem } from './types'

/**
 * What an answer points at.
 *
 * Numbered, titled, with the snippet the answer drew on, and a link where
 * the page can open the source. Nothing is retrieved by default in a product;
 * this renders whatever a product's retriever returns once one exists.
 */
export function AICitations({ title, citations }: { title: string; citations: AICitationItem[] }) {
  if (citations.length === 0) return null
  return (
    <div className="rounded-brand border border-line bg-surface-muted px-3 py-2 text-xs">
      <p className="font-semibold text-ink">{title}</p>
      <ol className="mt-1 list-decimal space-y-1 pl-4 text-ink-muted">
        {citations.map((citation, index) => (
          <li key={`${citation.title}-${index}`}>
            {citation.href ? (
              <a href={citation.href} className="font-medium text-brand hover:underline">
                {citation.title}
              </a>
            ) : (
              <span className="font-medium text-ink">{citation.title}</span>
            )}
            <span className="block">{citation.snippet}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
