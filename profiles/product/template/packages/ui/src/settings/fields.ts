import type { SettingValue } from './types'

/**
 * A setting as a page has prepared it for rendering.
 *
 * The definition arrives from the API carrying i18n *keys*; the page resolves
 * them with the request's translator and hands this down. So the component
 * holds no catalogue, no translator and no sentence of English — the rule
 * `product-frontend.test.ts` enforces across this package — and a product
 * speaking a language the API has never heard of still renders its own words.
 */
export interface SettingFieldOption {
  value: string
  label: string
}

export interface SettingField {
  key: string
  label: string
  description: string
  dataType: 'boolean' | 'integer' | 'decimal' | 'string' | 'enum' | 'string_list' | 'object'
  ui: 'toggle' | 'select' | 'number' | 'text' | 'chips'
  options: SettingFieldOption[]
  minimum: number | null
  maximum: number | null
  /** What this scope holds, or the inherited value when it holds nothing. */
  value: SettingValue
  /**
   * Whether this scope has a value of its own.
   *
   * The whole difference between "this is what you were given" and "this is
   * what somebody chose", which is what the reset control and the status
   * marker both hang on. A surface deriving it by comparing against the
   * inherited value gets it wrong the moment somebody deliberately sets a
   * value equal to it.
   */
  isSet: boolean
  /** What would apply if this scope held nothing: the next rung down. */
  inherited: SettingValue
}

export interface SettingGroup {
  /** The category's own name, for `data-category` and for React's key. */
  category: string
  title: string
  fields: SettingField[]
}

/**
 * The words the settings form needs, in the caller's language.
 *
 * `reset` is a verb on a button and `resetTo` is the sentence beside it, which
 * names the value it would restore — a reset that does not say what it gives
 * you is a reset nobody presses twice.
 */
export interface SettingsFormLabels {
  save: string
  saving: string
  /** Marks a field this scope has a value of its own for. */
  modified: string
  /** Marks a field showing what it was given. */
  inheritedFrom: string
  reset: string
  /** `{value}` — what pressing reset would leave behind. */
  resetTo: (value: string) => string
  /** For a list control, so a person knows how to separate entries. */
  listHint: string
  on: string
  off: string
}

/**
 * A value as a person reads it, for the marker beside a field.
 *
 * Deliberately not a formatter with locale rules. These are configuration
 * values — a number of rows, a file extension, an option somebody picked from
 * a list — and the option labels have already been resolved by the page. What
 * is left is joining a list and saying yes or no.
 */
export function describeValue(value: SettingValue, labels: SettingsFormLabels): string {
  if (typeof value === 'boolean') return value ? labels.on : labels.off
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/**
 * The label a value is shown by, when the field offers a closed list.
 *
 * Falls back to the raw value rather than to an empty string: a stored option
 * that has since been withdrawn should read as itself, not as nothing. The
 * resolver already refuses to *apply* such a value, so what reaches here is
 * either current or interesting.
 */
export function optionLabel(field: SettingField, value: SettingValue): string {
  const match = field.options.find((option) => option.value === String(value))
  return match ? match.label : String(value)
}
