/**
 * What the Files page may say about one file's content (ADR 0013, `secure_files`).
 *
 * The rule is the server's: `content_available` is computed there by the one
 * release predicate (`core/file_release.py`) and this file only reads it. What
 * it adds is a *closed* reading with a fail-closed default, so the page can
 * never invent a third thing to show:
 *
 * - `available`   -- the server says the content may be released;
 * - `scanning`    -- not yet released, and the stored verdict is the one a check
 *                    can still change (`pending`);
 * - `unavailable` -- everything else: `skipped`, `infected`, a missing value, a
 *                    value this build has never heard of, or an API that predates
 *                    the field. One neutral state, so nothing a scanner said and
 *                    nothing about *why* reaches a person who cannot act on it.
 *
 * A contradiction (`content_available` true beside a verdict that is not
 * `clean`) reads as `unavailable`. The server cannot produce one; the page
 * refusing to guess which half is right costs nothing and cannot release.
 *
 * None of this authorises anything. The download route asks the same rule
 * again for every request, so a stale or forged client state ends in a refusal,
 * never in bytes.
 */
export type FileAvailability = 'available' | 'scanning' | 'unavailable'

/** The two fields of a listed file the reading is made from. Structural, so any list row fits. */
export interface Releasable {
  content_available?: boolean | null
  scan_status?: unknown
}

export function availabilityOf(file: Releasable): FileAvailability {
  if (file.content_available === true) {
    return file.scan_status === 'clean' ? 'available' : 'unavailable'
  }
  return file.scan_status === 'pending' ? 'scanning' : 'unavailable'
}

export function anyScanning(files: readonly Releasable[]): boolean {
  return files.some((file) => availabilityOf(file) === 'scanning')
}

/**
 * The refusals the download route gives for a file that is not releasable, by
 * the API's own code. Both end in the same neutral sentence on the page and in
 * a re-read of the list: the file's state has moved on from what the page held.
 */
export const RELEASE_REFUSALS: ReadonlySet<string> = new Set(['file_scan_pending', 'file_quarantined'])

/**
 * How long a page left open on a file that is being checked keeps asking.
 *
 * A new upload is unavailable for at least the upload window (about sixteen
 * minutes, ADR 0013) plus the scanner's own time, so a few seconds
 * of polling would give up long before the answer and a fast loop would spend
 * the API's budget on a wait nobody can shorten. The delay therefore doubles
 * from ten seconds to a minute and stays there, and the whole wait ends at a
 * fixed deadline. Past it the page says so and offers one explicit refresh.
 *
 * A file that stays `pending` for ever -- one the scanner could not read, say -- costs
 * one open page at most thirty minutes of a few dozen reads, then nothing.
 */
export const POLL_FIRST_MS = 10_000
export const POLL_MAX_MS = 60_000
export const POLL_DEADLINE_MS = 30 * 60_000

/** The wait before poll number `attempt` (0-based). */
export function pollDelay(attempt: number): number {
  return Math.min(POLL_FIRST_MS * 2 ** Math.max(0, attempt), POLL_MAX_MS)
}
