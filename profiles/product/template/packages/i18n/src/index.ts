import { en } from './messages/en.js'
import { de } from './messages/de.js'
import { es } from './messages/es.js'

/**
 * Languages, for the whole product.
 *
 * One package and no dependency. Every string the interface shows a person is a
 * key in `messages/en.ts`, every other catalogue is typed against that file, and
 * a translator is a function of a locale -- which is what lets a server
 * component, a client component and a route handler all speak the same language
 * without a provider, a context or a request-scoped store. The locale crosses
 * the server/client boundary as a two-letter string, and everything else is
 * derived from it wherever it is needed.
 *
 * **Which languages exist is decided twice, and the split is deliberate.**
 * `SUPPORTED_LOCALES` below is what this package can *speak*: the catalogues
 * that have been written. `productConfig.i18n.locales` in `packages/branding`
 * is what a product *offers*: the subset it has reviewed and wants a switcher
 * to show. A catalogue can exist without being offered; a locale cannot be
 * offered without a catalogue, because the type refuses it.
 *
 * Deliberately free of React, of `next/*` and of the branding package. The
 * negotiation runs in a route handler, the translator runs in the browser, and
 * the catalogues are read by a test that has none of those.
 */

export const SUPPORTED_LOCALES = ['en', 'de', 'es'] as const

export type Locale = (typeof SUPPORTED_LOCALES)[number]

/**
 * Every key the English catalogue declares.
 *
 * English is the source of truth because it is the language the product is
 * written in. A key added there and nowhere else fails the German catalogue's
 * typecheck, which is the whole mechanism: a string that reaches a screen in
 * one language and not another is caught by `tsc`, not by a customer.
 */
export type MessageKey = keyof typeof en

export type Messages = Readonly<Record<MessageKey, string>>

export const MESSAGES: Readonly<Record<Locale, Messages>> = { en, de, es }

/**
 * Each language's own name for itself.
 *
 * Static rather than `Intl.DisplayNames`, because a switcher labelled from the
 * *current* language ("German") is a switcher the person who needs it cannot
 * read. A language is always offered in itself.
 */
export const LOCALE_NAMES: Readonly<Record<Locale, string>> = {
  en: 'English',
  de: 'Deutsch',
  es: 'Español',
}

/**
 * The cookie that remembers a visitor's choice.
 *
 * A cookie rather than `localStorage`, unlike the theme, because the *server*
 * has to know: the document's `lang`, its metadata and every string in the
 * first paint are rendered before any script runs. Set by the `/api/locale`
 * route handler and read on every request. It authorises nothing and is
 * validated against the offered list before it is used.
 */
export const LOCALE_COOKIE = 'koras-locale'

/** Scripts written right to left. None is shipped yet; the seam is here so `dir` is never hardcoded. */
const RTL_LOCALES: ReadonlySet<string> = new Set(['ar', 'he', 'fa', 'ur'])

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

export function localeDirection(locale: Locale): 'ltr' | 'rtl' {
  return RTL_LOCALES.has(locale.split('-')[0] ?? locale) ? 'rtl' : 'ltr'
}

/**
 * Pick the best of the offered locales for an `Accept-Language` header.
 *
 * Quality-ordered, then exact tag first and language-only second, so `de-AT`
 * finds `de` and `en-GB;q=0.9, de;q=0.8` finds `en`. A header naming nothing on
 * offer, a malformed header and no header at all answer the fallback -- there
 * is no error state here, because a visitor with an unusual browser should get
 * the product's default language rather than a 500.
 */
export function negotiateLocale(
  acceptLanguage: string | null | undefined,
  available: readonly Locale[],
  fallback: Locale,
): Locale {
  if (!acceptLanguage) return fallback

  const ranked = acceptLanguage
    .split(',')
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(';')
      const q = params.map((param) => param.trim()).find((param) => param.startsWith('q='))
      const quality = q === undefined ? 1 : Number.parseFloat(q.slice(2))
      return {
        tag: (tag ?? '').trim().toLowerCase(),
        quality: Number.isNaN(quality) ? 0 : quality,
        index,
      }
    })
    .filter((entry) => entry.tag !== '' && entry.quality > 0)
    .sort((a, b) => b.quality - a.quality || a.index - b.index)

  for (const { tag } of ranked) {
    const exact = available.find((locale) => locale.toLowerCase() === tag)
    if (exact !== undefined) return exact
    const language = tag.split('-')[0]
    const byLanguage = available.find(
      (locale) => locale.toLowerCase().split('-')[0] === language,
    )
    if (byLanguage !== undefined) return byLanguage
  }
  return fallback
}

/**
 * The locale for one request, in the order the sources are trusted.
 *
 *   1. the cookie the visitor set through the switcher
 *   2. the browser's `Accept-Language`
 *   3. the product's default
 *
 * A cookie naming a locale the product does not offer is ignored rather than
 * honoured: the value came from a browser, and a product that stopped offering
 * a language should stop rendering it. Nothing here reads a URL, because a
 * locale in a query string is a locale somebody can put in a link.
 */
export function resolveLocale(
  input: { cookie?: string | null; acceptLanguage?: string | null },
  available: readonly Locale[],
  fallback: Locale,
): Locale {
  if (isLocale(input.cookie) && available.includes(input.cookie)) return input.cookie
  return negotiateLocale(input.acceptLanguage, available, fallback)
}

/**
 * A path the locale route may send a visitor back to.
 *
 * Same-origin, absolute paths only. `//evil.example` is a protocol-relative URL
 * and a backslash is what some browsers turn into one, so both are refused; so
 * is anything not starting with `/`, and so is anything carrying whitespace or
 * a control character, because a header built from one is how a redirect
 * target grows a second line. The refusal answers `/` rather than an error,
 * because "change my language" is not a request whose failure anyone should
 * have to read about.
 */
export function safeReturnPath(next: unknown): string {
  if (typeof next !== 'string') return '/'
  if (!next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/'
  if (/\s/.test(next)) return '/'
  // Spelled out rather than as a character class: a control character inside a
  // regular expression is what `no-control-regex` refuses, and a code point
  // comparison says the same thing legibly.
  for (const character of next) {
    const code = character.codePointAt(0) ?? 0
    if (code < 0x20 || code === 0x7f) return '/'
  }
  return next
}

export type MessageParams = Readonly<Record<string, string | number>>

export type Translator = (key: MessageKey, params?: MessageParams) => string

/**
 * Fill `{name}` placeholders.
 *
 * Single braces, deliberately: these catalogues are read by files that are also
 * Handlebars templates, and a doubled brace is the delimiter the generator
 * looks for. A placeholder with no value is left visible rather than replaced
 * with nothing, so the gap is seen in review instead of shipped as a sentence
 * with a hole in it.
 */
export function interpolate(message: string, params?: MessageParams): string {
  if (params === undefined) return message
  return message.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = params[name]
    return value === undefined ? whole : String(value)
  })
}

/**
 * A translator for one locale.
 *
 * Falls back to English for a key whose translation is the empty string, so a
 * catalogue can be committed with a line left blank on purpose and the page
 * still says something. A key missing altogether cannot happen: the type of
 * every catalogue forbids it.
 */
export function createTranslator(locale: Locale): Translator {
  const messages = MESSAGES[locale]
  return (key, params) => {
    const message = messages[key] !== '' ? messages[key] : en[key]
    return interpolate(message, params)
  }
}

/** A date, in the locale's own conventions. `undefined` and invalid dates render as an empty string. */
export function formatDate(
  locale: Locale,
  value: Date | string | number | undefined,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' },
): string {
  if (value === undefined) return ''
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(locale, options).format(date)
}

/** A number, in the locale's own conventions: `1.234,5` in German, `1,234.5` in English. */
export function formatNumber(
  locale: Locale,
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(locale, options).format(value)
}

/**
 * Which plural form a count takes, for a catalogue that keeps one key per form.
 *
 * `Intl.PluralRules` rather than `count === 1`: the rule differs by language,
 * and hardcoding the English one is how "1 Einträge" happens.
 */
export function pluralCategory(locale: Locale, count: number): Intl.LDMLPluralRule {
  return new Intl.PluralRules(locale).select(count)
}
