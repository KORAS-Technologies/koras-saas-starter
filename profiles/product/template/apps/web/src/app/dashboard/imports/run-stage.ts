/**
 * Where an import run is in the wizard, decided from what the server persisted.
 *
 * Plain TypeScript with no generated import, like `source-state.ts`, so a test
 * executes it. The stage is **derived**, never stored in React state alone: a
 * person who refreshes, goes back, or opens a run from Recent imports gets the
 * stage the run is really in, because the run's `status` is the only input
 * that matters. The two booleans are things a person did on this page and are
 * deliberately not persisted -- `reviewed` only decides whether the Confirm
 * button is on screen yet, and a refresh puts the person back at Review, which
 * is the safe direction (nothing is ever committed by arriving anywhere).
 *
 *   Upload -> Map -> Validate -> Review -> Confirm -> Processing -> Results
 */

export type Stage = 'upload' | 'map' | 'validate' | 'review' | 'confirm' | 'processing' | 'results'

export const STAGES: readonly Stage[] = [
  'upload',
  'map',
  'validate',
  'review',
  'confirm',
  'processing',
  'results',
]

/** The run states in which the API accepts a mapping and a dry run. */
export const MAPPABLE_STATUSES: ReadonlySet<string> = new Set([
  'created',
  'mapped',
  'validated',
  'validation_failed',
])

export interface StageInput {
  /** The open run's status, or null when no run is open (the person is at Upload). */
  status: string | null
  /** Who confirmed it; null until somebody does. Tells a failed dry run from a failed commit. */
  committedBy: string | null
  /** The person pressed "Continue to confirmation" on this page. */
  reviewed: boolean
  /** The person asked to change the mapping of a checked run. */
  remap: boolean
}

/**
 * The stage a run is in, or `null` for a run that has ended without a result
 * (cancelled): it has no current step, and the page says so rather than
 * lighting one up.
 */
export function stageOf(input: StageInput): Stage | null {
  switch (input.status) {
    case null:
      return 'upload'
    case 'created':
    case 'mapped':
      return 'map'
    case 'validating':
      return 'validate'
    case 'validation_failed':
      return input.remap ? 'map' : 'validate'
    case 'validated':
      if (input.remap) return 'map'
      return input.reviewed ? 'confirm' : 'review'
    case 'commit_requested':
    case 'committing':
      return 'processing'
    case 'committed':
      return 'results'
    case 'failed':
      // A run nobody confirmed failed while it was being checked; one somebody
      // confirmed failed while it was being written.
      return input.committedBy === null ? 'validate' : 'processing'
    case 'cancelled':
      return null
    default:
      // A state this build has never heard of is not placed anywhere.
      return null
  }
}

/** Steps before the current one are done; a null stage marks nothing done. */
export function stepState(step: Stage, current: Stage | null): 'done' | 'current' | 'todo' {
  if (current === null) return 'todo'
  const at = STAGES.indexOf(step)
  const now = STAGES.indexOf(current)
  if (at < now) return 'done'
  return at === now ? 'current' : 'todo'
}

/**
 * A moment as the reader's own clock shows it. Storage and the API stay UTC;
 * only the sentence changes. `zone` is passed in the first render (UTC, so the
 * server and the browser agree and hydration is exact) and left out afterwards.
 */
export function formatWhen(iso: string, locale: string, zone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  try {
    const text = new Intl.DateTimeFormat(locale || 'en', {
      dateStyle: 'medium',
      timeStyle: 'short',
      ...(zone === undefined ? {} : { timeZone: zone }),
    }).format(date)
    return zone === 'UTC' ? `${text} UTC` : text
  } catch {
    return iso
  }
}

/** The `?run=` value of a URL search string, or null when it is not a run id. */
export function runIdFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get('run')
  return value !== null && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
    ? value.toLowerCase()
    : null
}
