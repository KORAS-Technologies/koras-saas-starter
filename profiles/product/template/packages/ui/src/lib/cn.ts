/**
 * Join class names, dropping anything falsy.
 *
 * Deliberately not `clsx` + `tailwind-merge`. Those exist to resolve conflicts
 * between classes composed from several places; nothing here composes that way,
 * because every component in this package owns its own classes and takes a
 * single optional `className` appended last. Two dependencies to solve a
 * problem the component shapes already avoid is a poor trade in a package that
 * ships into every generated product.
 */
export type ClassValue = string | false | null | undefined

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(' ')
}
