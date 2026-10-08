/**
 * What the Import page may say about a file it has uploaded, between "the
 * bytes reached the bucket" and "a run can start".
 *
 * Plain TypeScript with no generated import, on purpose: the generator suite
 * imports this module and executes it (the way it does `form-values.ts`), so
 * the wait's schedule and the remembered entry are tested rather than read.
 *
 * **`pending` is not `missing`.** A new upload is withheld from every consumer
 * until it has been finalized and scanned, which takes most of twenty minutes
 * by design (the upload window in `core/upload_window.py`, `secure_files`).
 * Starting a run in that window used to be refused with the same sentence as a
 * quarantined file, so a perfectly good file read as a rejected one. The page
 * now asks the API where the source is (`GET /imports/sources/{id}`, read-only,
 * a closed word) and starts the run only on `ready`, which is the one release
 * rule saying yes. Nothing here decides that; it only waits for the server to.
 *
 * The phases a person sees, in order:
 *   `checking` -> `ready` (then the run starts),
 * and the ends that are not a success: `held`, `rejected`, `missing`, plus
 * `stalled` for a wait that outlived the page's patience while the file is
 * still being checked, which is not a verdict on the file.
 */

/** The server's closed answer; the api-client's `ImportSourceState` is this type. */
export type SourceAnswer = 'checking' | 'ready' | 'held' | 'rejected' | 'missing'

export type SourcePhase = 'idle' | SourceAnswer | 'stalled'

/** What the answer from the server means for the page. Closed, fail-closed. */
export function phaseOf(state: SourceAnswer | string): SourcePhase {
  switch (state) {
    case 'ready':
      return 'ready'
    case 'checking':
      return 'checking'
    case 'held':
      return 'held'
    case 'rejected':
      return 'rejected'
    // Anything this build has never heard of is treated as "no longer there",
    // never as ready.
    default:
      return 'missing'
  }
}

/** Whether the page keeps asking. Only `checking` is a wait. */
export function isWaiting(phase: SourcePhase): boolean {
  return phase === 'checking'
}

/**
 * The wait before check number `attempt` (0-based): ten seconds doubling to a
 * minute. The wait is the upload window plus the scanner, nobody can shorten
 * it, and a fast loop would spend the API's budget on it.
 */
export const CHECK_FIRST_MS = 10_000
export const CHECK_MAX_MS = 60_000

/** Past this the page stops asking and offers one explicit "Check again". */
export const CHECK_DEADLINE_MS = 45 * 60_000

export function checkDelay(attempt: number): number {
  return Math.min(CHECK_FIRST_MS * 2 ** Math.max(0, attempt), CHECK_MAX_MS)
}

/**
 * What the page remembers about an upload that is still being checked, so
 * a person who closes the tab for twenty minutes can come back and carry on.
 * Only identifiers and the labels the page already showed; never bytes, never
 * a token. It is a convenience: the server decides, and a file that is not this
 * organisation's reads as `missing` and the entry is dropped.
 */
export interface PendingSource {
  fileId: string
  name: string
  size: number
  target: string
  operation: string
  at: number
}

export const PENDING_KEY = 'koras.imports.pending-source'

/**
 * One entry per signed-in person and organisation. A browser shared by two
 * people must not hand one the other's file name, nor let a restored wait act
 * for someone it was not made by; with no scope the bare key is used.
 */
export function pendingKey(scope: string): string {
  return scope === '' ? PENDING_KEY : `${PENDING_KEY}:${scope}`
}

/** Old enough that the file is certainly done or gone: not offered again. */
export const PENDING_MAX_AGE_MS = 24 * 60 * 60_000

export function parsePending(raw: string | null, now: number): PendingSource | null {
  if (raw === null) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null) return null
    const v = value as Record<string, unknown>
    if (
      typeof v.fileId !== 'string' ||
      typeof v.name !== 'string' ||
      typeof v.size !== 'number' ||
      typeof v.target !== 'string' ||
      typeof v.operation !== 'string' ||
      typeof v.at !== 'number'
    ) {
      return null
    }
    if (now - v.at > PENDING_MAX_AGE_MS || v.at > now + 60_000) return null
    return {
      fileId: v.fileId,
      name: v.name,
      size: v.size,
      target: v.target,
      operation: v.operation,
      at: v.at,
    }
  } catch {
    return null
  }
}
