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
