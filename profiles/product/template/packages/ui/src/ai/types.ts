/**
 * What the assistant components render. Plain data, already translated.
 *
 * These components make no decision and read nothing: the page builds the
 * items from the API's answer and the labels from the caller's language, and
 * passes both down, the way `FilesPanel` is given its labels. That is what
 * lets every one of them stay a plain `.tsx` with no template variable in it
 * -- and what keeps a component that runs in the browser from ever holding
 * the API's address or the caller's token.
 */

export interface AIMessageItem {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  /** Set on a tool message: which tool answered. */
  toolName?: string | null
  createdAt: string
}

export interface AIActionItem {
  id: string
  toolId: string
  /** The action in words, for the person deciding. */
  summary?: { title: string; detail: string } | null
  operation: 'read' | 'write' | 'destructive' | 'external'
  status: string
  input: Record<string, unknown>
  result?: Record<string, unknown> | null
  error?: string | null
  createdAt: string
}

export interface AICitationItem {
  title: string
  snippet: string
  href?: string
}

export interface AIConversationLabels {
  you: string
  speaker: string
  empty: string
  emptyHint: string
  toolResult: string
  toolResultShow: string
}
