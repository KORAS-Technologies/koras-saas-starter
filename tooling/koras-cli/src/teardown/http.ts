import type { FetchLike } from '../doctor/types.js'
import { HttpError, DEFAULT_TIMEOUT_MS, safeHost } from '../doctor/http.js'

/**
 * DELETE, which the doctor's client deliberately cannot do.
 *
 * `doctor/http.ts` types its method as `'GET' | 'POST'` and says in its own
 * comment that nothing there can create, modify or delete a resource. That type
 * is the guarantee. Widening it so teardown could share the function would
 * remove the guarantee from the doctor to save a dozen lines here, which is the
 * wrong trade -- the doctor runs against a live estate far more often than this
 * ever will.
 *
 * So the destructive verb lives with the destructive command, and the read-only
 * client stays read-only.
 */

export async function del(
  fetchImpl: FetchLike,
  url: string,
  headers: Record<string, string>,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<void> {
  let timer: NodeJS.Timeout | undefined
  const host = safeHost(url)

  const response = await Promise.race([
    fetchImpl(url, { method: 'DELETE', headers }).finally(() => clearTimeout(timer)),
    new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`${host} did not respond within ${timeoutMs}ms.`)),
        timeoutMs,
      )
      timer.unref?.()
    }),
  ])

  if (!response.ok) throw new HttpError(response.status, await response.text())
}

/**
 * GET, for asking whether a resource is still there.
 *
 * Same reasoning as `del` above, and one more: `--verify` must ask about the
 * *same URL* the deleter used, or it is checking something else and reporting
 * it as proof. Both go through `providerEndpoints`, so a probe cannot drift
 * from the delete it is verifying.
 *
 * Returns the status rather than throwing on a non-2xx, because every status is
 * an answer here: 404 is gone, 2xx is alive, and anything else is neither and
 * must not be reported as either.
 */
export async function probe(
  fetchImpl: FetchLike,
  url: string,
  headers: Record<string, string>,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<number> {
  let timer: NodeJS.Timeout | undefined
  const host = safeHost(url)

  const response = await Promise.race([
    fetchImpl(url, { method: 'GET', headers }).finally(() => clearTimeout(timer)),
    new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`${host} did not respond within ${timeoutMs}ms.`)),
        timeoutMs,
      )
      timer.unref?.()
    }),
  ])

  // Drain it. A GET whose body is never read leaves the socket open, and undici
  // keeps it in its pool; the process then exits with handles still live and
  // Node aborts on Windows with
  // `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), src\win\async.c`
  // and exit code 3221226505 -- after printing a correct result, which is the
  // confusing part. Nothing is wrong with the answer; the process cannot leave.
  //
  // `del` has never needed this: it reads the body on failure and its
  // successful responses are empty, so nothing is left buffered.
  try {
    await response.text()
  } catch {
    // A body that cannot be read is not an error about the resource.
  }

  return response.status
}
