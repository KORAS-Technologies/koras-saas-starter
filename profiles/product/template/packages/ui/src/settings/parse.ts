import type { EffectiveSettings, ResolvedSetting, SettingSource, SettingValue } from './types'

/**
 * What the API said, checked into something a component may render.
 *
 * The same seam `parseTenantBranding` sits on, and for the same reason: an
 * answer from the network is data until something has looked at it, and a
 * component that trusted it would be a component that crashes on a response
 * from a version of the API it was not built against.
 *
 * It is also what keeps the two types apart honestly. `packages/api-client`
 * describes the wire, where a value is `unknown` because a setting's type lives
 * in the catalogue and not in an HTTP client. This describes what has been
 * checked. They were the same name for one commit; every package typechecked
 * and the application importing both did not.
 *
 * **Never throws, and drops rather than refuses.** One malformed entry costs
 * that setting, not the page: the component falls back to the value it would
 * have used anyway, which is exactly what it does when the API is unreachable.
 * Refusing the whole answer would mean one unrecognised setting unstyles the
 * product.
 */
export function parseEffectiveSettings(raw: unknown): EffectiveSettings | null {
  if (!isRecord(raw)) return null
  const rawSettings = raw['settings']
  if (!isRecord(rawSettings)) return null

  const settings: Record<string, ResolvedSetting> = {}
  for (const [key, entry] of Object.entries(rawSettings)) {
    const resolved = parseResolved(key, entry)
    if (resolved !== null) settings[key] = resolved
  }

  const skipped = Array.isArray(raw['skipped'])
    ? raw['skipped'].filter((entry): entry is string => typeof entry === 'string')
    : []

  return { settings, skipped }
}

const SOURCES: readonly SettingSource[] = ['user', 'organization', 'global', 'default']

function parseResolved(key: string, raw: unknown): ResolvedSetting | null {
  if (!isRecord(raw)) return null

  const value = parseValue(raw['value'])
  if (value === undefined) return null

  const source = raw['source']
  if (typeof source !== 'string' || !SOURCES.includes(source as SettingSource)) return null

  // The two fallbacks may legitimately be missing from an older answer, and a
  // setting is still usable without them — only the reset controls need them,
  // and they can say so. Defaulting to the value itself keeps every consumer
  // from having to test for undefined.
  const organization = parseValue(raw['organization_value']) ?? value
  const global = parseValue(raw['global_value']) ?? value

  return {
    // The map's key, not the entry's. If they ever disagree, the map is what a
    // caller looked the setting up by.
    key,
    value,
    source: source as SettingSource,
    can_override: raw['can_override'] === true,
    organization_value: organization,
    global_value: global,
  }
}

/**
 * One value, if it is one of the types a setting can hold.
 *
 * `undefined` means "not a setting value", which is why it is the return for a
 * rejection: `null` is a value JSON has and `undefined` is not, so a row
 * holding null is refused here rather than being mistaken for an absence the
 * caller should fall back through.
 *
 * A list is accepted only when every entry is a string, because
 * `STRING_LIST` is the only list type the catalogue has. A mixed list is a
 * value no definition could have produced.
 */
function parseValue(raw: unknown): SettingValue | undefined {
  if (typeof raw === 'boolean' || typeof raw === 'number' || typeof raw === 'string') return raw
  if (Array.isArray(raw)) {
    return raw.every((entry) => typeof entry === 'string') ? (raw as string[]) : undefined
  }
  if (isRecord(raw)) return raw
  return undefined
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw)
}
