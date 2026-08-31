import { redirect } from 'next/navigation'

/**
 * `/signin`, kept as an alias of `/login`.
 *
 * `/login` is the canonical route and stays that way: it is what the middleware
 * redirects to, what the sign-out route returns to, and what the deployment
 * smoke checks assert. Two live sign-in pages would be two things to keep in
 * step, so this one is a redirect and holds no markup of its own.
 *
 * It exists because `/signin` is what people type and what half the writing
 * about this product will link to, and a 404 on the way to signing in is an
 * expensive way to be right about a route name.
 *
 * `next` is forwarded rather than dropped -- otherwise a link that carried a
 * destination through this alias would silently lose it and land the person on
 * the dashboard instead of where they were going.
 */
export default async function SignInAlias({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams
  redirect(next ? `/login?next=${encodeURIComponent(next)}` : '/login')
}
