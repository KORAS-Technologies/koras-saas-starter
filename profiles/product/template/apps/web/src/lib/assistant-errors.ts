/**
 * Which sentence a refusal from the assistant's API gets.
 *
 * Pure, so both halves can use it: the server actions translate the key with
 * the request's translator, and the panel -- which receives a refusal inside
 * a stream, after the response has begun -- picks the same key out of the
 * labels it was handed. One mapping, two readers, no catalogue in the bundle.
 */

export type AssistantErrorKey =
  'plan' | 'forbidden' | 'limit' | 'unavailable' | 'timeout' | 'generic'

export function assistantErrorKey(
  code: string | null | undefined,
  status: number,
): AssistantErrorKey {
  switch (code) {
    case 'entitlement_missing':
      return 'plan'
    case 'tool_denied':
      return 'forbidden'
    case 'usage_exceeded':
      return 'limit'
    case 'timeout':
      return 'timeout'
    case 'provider_unavailable':
    case 'configuration_error':
    case 'upstream_error':
      return 'unavailable'
    default:
      break
  }
  if (status === 402) return 'plan'
  if (status === 403) return 'forbidden'
  if (status === 429) return 'limit'
  if (status === 502 || status === 503) return 'unavailable'
  if (status === 504) return 'timeout'
  return 'generic'
}
