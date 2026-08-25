import { describe } from 'vitest'

/**
 * The line between an acceptance test and a bill.
 *
 * Everything in `tests/e2e` runs by default except the parts that would
 * contact a real provider. Those are gated here, on an environment variable
 * nobody sets by accident, so that `pnpm test` on a laptop or in CI cannot
 * create a GitHub repository, a Supabase project, or a Fly app.
 *
 * The gate is deliberately one variable rather than "are credentials
 * present": a developer with Doppler configured has credentials present all
 * day, and that must not be what decides whether a test provisions an estate.
 */

export function liveMode(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.KORAS_E2E_LIVE === '1'
}

/**
 * `describe` for suites that touch real infrastructure.
 *
 * Skipped unless the gate is open, and named so the skip reason is visible in
 * the report rather than looking like a suite nobody wrote.
 *
 * A function rather than `liveMode() ? describe : describe.skip`: that union
 * is typed with vitest internals this module cannot name, so it fails
 * declaration emit. Dispatching inside keeps the signature ordinary.
 */
export function describeLive(name: string, fn: () => void): void {
  if (liveMode()) describe(name, fn)
  else describe.skip(name, fn)
}
