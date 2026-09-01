/**
 * Which workspace this session is acting for.
 *
 * A badge, not a switcher, and the difference is not a design preference. A
 * session in this product carries exactly one organization: it is derived from
 * the verified token, and `packages/auth` refuses a token that names two rather
 * than picking one. Switching would mean obtaining a new token from the
 * identity provider, not changing a value in the browser — so a control that
 * looked like a switcher would be a control that cannot switch.
 *
 * When a product does grow multi-workspace access, this is the component that
 * becomes the switcher, and the rule it must keep is the one that matters: an
 * organization the caller may not act for never appears in the list. A switcher
 * populated from anything other than the caller's own verified grants is a
 * cross-tenant enumeration surface with a chevron on it.
 *
 * Renders nothing at all when there is no organization to name. An empty pill
 * beside the logo reads as a value that failed to load.
 */
export function WorkspaceBadge({ name }: { name?: string }) {
  if (name === undefined || name.trim() === '') return null

  return (
    <span className="hidden items-center gap-2 sm:inline-flex">
      <span aria-hidden="true" className="h-5 w-px bg-line" />
      <span className="max-w-48 truncate rounded-brand bg-surface-muted px-2.5 py-1 text-sm font-medium text-ink-muted">
        <span className="sr-only">Workspace: </span>
        {name}
      </span>
    </span>
  )
}
