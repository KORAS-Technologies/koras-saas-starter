import { Fragment } from 'react'
import type { ReactNode } from 'react'

/**
 * Inline markup in a translated string, rendered as elements.
 *
 * A catalogue message may carry `<code>…</code>`, `<a>…</a>` or
 * `<strong>…</strong>`; this maps each tag to whatever the caller renders for
 * it. The alternative -- splitting one sentence into `before`, `link` and
 * `after` keys -- makes a translator assemble grammar out of fragments, and
 * German does not put its verbs where English does.
 *
 * Not HTML. The string is never set as `innerHTML`; unknown tags render their
 * text and lose the brackets, and the text between tags is a React string
 * child, escaped like any other. A translation cannot inject an element the
 * caller did not offer a renderer for.
 *
 * Tags do not nest. None of the catalogue needs it, and the regular expression
 * is simpler for the promise.
 */
export type RichTags = Readonly<Record<string, (chunk: ReactNode) => ReactNode>>

export function rich(message: string, tags: RichTags): ReactNode {
  const pattern = /<(\w+)>([\s\S]*?)<\/\1>/g
  const nodes: ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(message)) !== null) {
    if (match.index > last) {
      nodes.push(<Fragment key={nodes.length}>{message.slice(last, match.index)}</Fragment>)
    }
    const tag = match[1] ?? ''
    const inner = match[2] ?? ''
    const render = tags[tag]
    nodes.push(<Fragment key={nodes.length}>{render ? render(inner) : inner}</Fragment>)
    last = match.index + match[0].length
  }
  if (last < message.length) {
    nodes.push(<Fragment key={nodes.length}>{message.slice(last)}</Fragment>)
  }
  return nodes
}

/** The one tag most of the catalogue uses: a file path or identifier, set in code. */
export function codeTag(chunk: ReactNode): ReactNode {
  return <code className="text-ink">{chunk}</code>
}

export function strongTag(chunk: ReactNode): ReactNode {
  return <strong className="font-medium text-ink">{chunk}</strong>
}
