import type { ReactNode } from 'react'
import { Card } from '../primitives/card'
import { Container } from '../primitives/container'

/**
 * What a signed-in caller sees when they may not have this page.
 *
 * A real state, not an edge case. In a multi-tenant product with roles, being
 * refused is as ordinary as being allowed, and a product whose only answer to
 * it is a blank screen or a redirect back to a page the caller has already
 * loaded is a product that looks broken to the person it is protecting.
 *
 * Deliberately says nothing about *what* is behind the refusal. "You need the
 * reports.manage permission" tells somebody probing the application which
 * permissions exist and which ones are worth acquiring; "ask an administrator"
 * tells the person who is legitimately stuck exactly what to do next, which is
 * the only thing they can act on either way.
 *
 * This is the page a route renders after the server has already refused. It is
 * **not** the refusal: the middleware and the page's own check are. A component
 * cannot be a boundary, because a component only runs once something has
 * decided to render it.
 */
export function AccessDenied({
  title = 'You do not have access to this page',
  description = 'Your account is signed in, but it does not have permission for this area. An administrator in your organisation can change that.',
  action,
}: {
  title?: string
  description?: string
  /** A way onward, when there is a sensible one. Usually a link home. */
  action?: ReactNode
}) {
  return (
    <div className="py-12">
      <Container>
        <Card className="max-w-2xl">
          <h1 className="font-display text-2xl font-bold tracking-tight text-ink">{title}</h1>
          <p className="mt-3 leading-7 text-ink-muted">{description}</p>
          {action !== undefined && <div className="mt-6">{action}</div>}
        </Card>
      </Container>
    </div>
  )
}
