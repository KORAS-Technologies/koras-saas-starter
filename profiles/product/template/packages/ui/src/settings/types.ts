/**
 * What a resolved setting looks like to a component.
 *
 * The API's own shape, unchanged: `can_override`, `organization_value` and
 * `global_value` keep their snake_case because that is what
 * `GET /api/v1/settings/effective` answers with, and `TenantSettings` in
 * `packages/api-client` already carries `member_locale` for the same reason.
 * One convention across the seam beats a prettier one on this side and a
 * mapping layer nobody asked for.
 */

/**
 * The types a setting can hold.
 *
 * The JSON types and nothing else, matching `SettingValue` in `koras_settings`:
 * a value is stored as `jsonb`, travels over an API and is rendered in a
 * browser, so a type that does not survive that round trip is a type a setting
 * cannot have.
 */
export type SettingValue = boolean | number | string | readonly string[] | Record<string, unknown>

/** Which rung of the ladder answered. */
export type SettingSource = 'user' | 'organization' | 'global' | 'default'

export interface ResolvedSetting {
  key: string
  value: SettingValue
  source: SettingSource
  /**
   * Whether this person could set a value of their own.
   *
   * False for every organisation-level setting, so a preferences page knows
   * what to offer without reading the scope itself.
   */
  can_override: boolean
  /** What would answer if this person cleared theirs. */
  organization_value: SettingValue
  /** What the platform holds, which is what an organisation reset copies in. */
  global_value: SettingValue
}

export interface EffectiveSettings {
  settings: Record<string, ResolvedSetting>
  /**
   * Keys whose stored value no longer satisfies its definition.
   *
   * Not an error. A bound tightened or an option withdrawn in a deploy leaves
   * rows that were valid when written; the resolver falls through to the next
   * level rather than refusing to render, and names here what it passed over.
   * A surface may show this to an administrator and must not fail on it.
   */
  skipped: string[]
}

/**
 * The settings this product declares, for the benefit of autocompletion.
 *
 * Not a second catalogue: no labels, no defaults, no rules, nothing a surface
 * decides anything from. Those live in `koras_settings` and reach the browser
 * through `GET /api/v1/settings/definitions`. This is the list of names, and
 * `product-settings.test.ts` keeps it level with `settings_catalogue/standard.py`.
 *
 * A product adding its own setting in `settings_catalogue/product.py` does not
 * have to add it here — see `SettingKey`.
 */
export const STANDARD_SETTING_KEYS = [
  'general.timezone',
  'general.language',
  'general.dateFormat',
  'general.timeFormat',
  'general.currency',
  'general.firstDayOfWeek',
  'ui.theme',
  'ui.density',
  'ui.sidebarCollapsed',
  'ui.defaultLandingPage',
  'grid.pageSize',
  'grid.pageSizeOptions',
  'grid.paginationEnabled',
  'grid.stickyHeader',
  'grid.allowColumnResize',
  'grid.allowColumnReorder',
  'grid.rememberFilters',
  'grid.rememberSort',
  'grid.rememberColumns',
  'grid.rowDensity',
  'notifications.inAppEnabled',
  'notifications.emailEnabled',
  'notifications.digestFrequency',
  'files.maxUploadSizeMb',
  'files.allowedExtensions',
  'files.maxFilesPerUpload',
  'files.previewEnabled',
  'reporting.defaultDateRange',
  'reporting.defaultExportFormat',
  'accessibility.reducedMotion',
  'accessibility.highContrast',
  'accessibility.fontScale',
] as const

/**
 * A setting's key.
 *
 * The intersection is deliberate and is not a mistake to be tidied away. It
 * keeps the union above as autocompletion while still accepting any string, so
 * a product that declares `shop.basketHoldMinutes` in its own catalogue can
 * read it without editing this package. Narrowing to the union alone would
 * make the foundation's list a ceiling on what a product may declare.
 *
 * `Record<never, never>` rather than the `{}` this idiom is usually written
 * with: the two are the same type, and `no-empty-object-type` flags one of
 * them. A rule suppression is a thing to keep right forever; a type that does
 * not need one is not.
 */
export type SettingKey =
  | (typeof STANDARD_SETTING_KEYS)[number]
  | (string & Record<never, never>)
