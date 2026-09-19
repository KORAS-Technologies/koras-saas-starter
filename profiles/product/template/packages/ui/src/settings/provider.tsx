'use client'

import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type { EffectiveSettings, ResolvedSetting, SettingKey, SettingValue } from './types'
import { settingValue } from './value'

/**
 * The settings a signed-in person's pages resolve against, loaded once.
 *
 * **Once per request, in the layout, on the server.** The dashboard layout
 * already resolves the caller's context, their locale and their tenant's
 * settings for every page beneath it; the effective settings join that load and
 * arrive here as plain data. No page fetches them, no component fetches them,
 * and a navigation costs one call rather than one per screen.
 *
 * That is not only an optimisation. Two components reading the same setting
 * through two requests can disagree — a person who changes their page size
 * mid-render would get a table paginated one way and a pager drawn the other —
 * and the shell's branding avoids exactly that by being resolved once, for the
 * same reason.
 *
 * **Nothing here decides anything.** The server resolved which rung of the
 * ladder won, and this hands out the answer. A provider that could re-resolve
 * is a provider somebody will eventually rely on to, in a bundle the caller
 * owns.
 */

const SettingsContext = createContext<EffectiveSettings | null>(null)

export function SettingsProvider({
  settings,
  children,
}: {
  /**
   * What the server resolved, or null when it could not.
   *
   * Null is a real state and not a bug: `effectiveSettings()` never throws, so
   * an API that is down gives a shell that renders with every component's own
   * fallback rather than a page that will not load. A settings lookup must not
   * be able to take the product down, which is the position
   * `lib/tenant-settings.ts` already takes for branding.
   */
  settings: EffectiveSettings | null
  children: ReactNode
}) {
  // Memoised on the object the server sent, so a re-render of the layout does
  // not give every consumer a new context value and re-render the whole tree.
  const value = useMemo(() => settings, [settings])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

/**
 * Everything resolved for this caller, or null outside a provider.
 *
 * Null rather than a throw. A component rendered outside the signed-in area —
 * in a test, in a story, on a marketing page that reuses a primitive — should
 * fall back to its own default, not crash the page it is on.
 */
export function useSettings(): EffectiveSettings | null {
  return useContext(SettingsContext)
}

/**
 * One setting's full answer: the value, where it came from, what a reset gives.
 *
 * For a surface that shows a setting *as* a setting — the preferences page, the
 * organisation's page — where "this is the default" and "somebody chose this"
 * are different things to say. A component that only needs the value should use
 * `useSettingValue`, which cannot be got wrong.
 */
export function useSetting(key: SettingKey): ResolvedSetting | undefined {
  return useSettings()?.settings[key]
}

/**
 * One setting's value, with the fallback this component would use anyway.
 *
 * The fallback is required, and that is the design. A shared component has to
 * work outside a provider and before the first load, so it needs a value it can
 * name; making it pass one keeps the foundation's defaults in `koras_settings`
 * rather than mirrored into a second table in TypeScript that would drift.
 *
 * The type is checked against what arrived, not asserted. A row holding a
 * string where a component expects a number — a definition changed under a
 * value that was valid when written — yields the fallback rather than a page
 * that renders `NaN` rows per page.
 */
export function useSettingValue<T extends SettingValue>(key: SettingKey, fallback: T): T {
  return settingValue(useSetting(key), fallback)
}
