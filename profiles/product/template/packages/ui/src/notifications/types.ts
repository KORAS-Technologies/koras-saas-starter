/**
 * What a rendered notification is, on the browser side.
 *
 * Deliberately not the API's shape with the field names changed: `createdAt`
 * is a string here because it crosses a server/client boundary and a `Date`
 * does not survive that intact, and `read` is a boolean because a component
 * asks "is it read", never "when".
 */
export type NotificationTone = 'info' | 'success' | 'warning' | 'error'

export type NotificationItem = {
  id: string
  /** The dotted kind, for a test to assert on. Never rendered. */
  kind: string
  title: string
  body: string
  /** Root-relative, or empty. The API refuses anything else. */
  url: string
  tone: NotificationTone
  /** ISO 8601, formatted by the component in the reader's locale. */
  createdAt: string
  read: boolean
}

/**
 * Every word these components draw, supplied by the application.
 *
 * No component in this package holds a sentence: the product's translations
 * live in `@<slug>/i18n` and the shell resolves them before it renders. A
 * default string here would be an English one shipped to a German customer.
 */
export type NotificationLabels = {
  /** The bell's accessible name, e.g. "Notifications". */
  title: string
  /** Announced beside the count, e.g. "{count} unread". */
  unread: (count: number) => string
  empty: string
  emptyHint: string
  markAllRead: string
  markRead: string
  dismiss: string
  close: string
  viewAll: string
}
