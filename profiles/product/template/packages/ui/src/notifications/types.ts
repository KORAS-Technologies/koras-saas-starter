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
/**
 * Fill the `{count}` placeholder in a label template.
 *
 * Single braces, matching the convention in `@<slug>/i18n`: these catalogues
 * are read by files that are also Handlebars templates, and a doubled brace is
 * the generator's own delimiter. A template with no placeholder is returned
 * unchanged, which is what a translation that phrases the count differently
 * should do.
 */
export function withCount(template: string, count: number): string {
  return template.replace(/\{count\}/g, String(count))
}

export type NotificationLabels = {
  /** The bell's accessible name, e.g. "Notifications". */
  title: string
  /**
   * Announced beside the count, e.g. "{count} unread".
   *
   * A TEMPLATE carrying `{count}` -- not a finished sentence, and deliberately
   * not a function. These labels are built in the dashboard layout, which is a
   * server component, and handed to the bell, which is a client one. React
   * cannot serialise a function across that boundary; it throws. And because
   * the bell lives in the layout, the throw takes down every signed-in page
   * rather than just the bell, which is how one unserialisable prop failed
   * seventy browser tests at once.
   *
   * Fill it with `withCount`.
   */
  unread: string
  empty: string
  emptyHint: string
  markAllRead: string
  markRead: string
  dismiss: string
  close: string
  viewAll: string
}
