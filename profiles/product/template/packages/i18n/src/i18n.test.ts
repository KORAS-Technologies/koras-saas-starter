import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  MESSAGES,
  SUPPORTED_LOCALES,
  createTranslator,
  formatNumber,
  interpolate,
  localeDirection,
  negotiateLocale,
  resolveLocale,
  safeReturnPath,
} from './index.js'
import { en } from './messages/en.js'

/**
 * The catalogues, and the negotiation that picks one.
 *
 * The typecheck already proves every catalogue has every key. What it cannot
 * prove is that a translation kept its placeholders and its inline tags, or
 * that a browser asking for `de-AT` is answered in German -- those are the
 * claims below.
 */

test('every catalogue carries the same placeholders as English', () => {
  const placeholders = (message: string) => [...message.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

  for (const locale of SUPPORTED_LOCALES) {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      const translated = MESSAGES[locale][key]
      if (translated === '') continue
      assert.deepEqual(
        placeholders(translated),
        placeholders(en[key]),
        `${locale}: "${key}" does not carry the placeholders the English message does`,
      )
    }
  }
})

test('every catalogue carries the same inline tags as English', () => {
  const tags = (message: string) => [...message.matchAll(/<(\w+)>/g)].map((m) => m[1]).sort()

  for (const locale of SUPPORTED_LOCALES) {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      const translated = MESSAGES[locale][key]
      if (translated === '') continue
      assert.deepEqual(tags(translated), tags(en[key]), `${locale}: "${key}" changed its inline tags`)
    }
  }
})

test('no catalogue contains a doubled brace', () => {
  // These strings are imported by files that are also Handlebars templates,
  // and a doubled brace is the expression delimiter the generator looks for.
  for (const locale of SUPPORTED_LOCALES) {
    for (const [key, message] of Object.entries(MESSAGES[locale])) {
      assert.ok(!message.includes('{{'), `${locale}: "${key}" contains a doubled brace`)
    }
  }
})

test('a translation is a real translation, not the English copied over', () => {
  // Names, symbols and technical tokens legitimately match. Prose does not,
  // and a German catalogue that matched English in a fifth of its keys would
  // be a catalogue somebody filled in by copying.
  for (const locale of SUPPORTED_LOCALES) {
    if (locale === 'en') continue
    const same = Object.keys(en).filter(
      (key) => MESSAGES[locale][key as keyof typeof en] === en[key as keyof typeof en],
    )
    assert.ok(
      same.length < Object.keys(en).length / 10,
      `${locale}: too many identical strings: ${same.join(', ')}`,
    )
  }
})

test('interpolation fills what it is given and leaves what it is not', () => {
  assert.equal(interpolate('Welcome to {product}', { product: 'Acme' }), 'Welcome to Acme')
  assert.equal(interpolate('{a} and {b}', { a: 1 }), '1 and {b}')
  assert.equal(interpolate('no placeholders'), 'no placeholders')
})

test('the translator speaks the requested language', () => {
  assert.equal(createTranslator('en')('common.signIn'), 'Sign in')
  assert.equal(createTranslator('de')('common.signIn'), 'Anmelden')
  assert.equal(createTranslator('de')('login.heading', { product: 'Acme' }), 'Bei Acme anmelden')
})

test('negotiation is quality-ordered and falls back by language', () => {
  const offered = ['en', 'de'] as const
  assert.equal(negotiateLocale('de-AT,de;q=0.9,en;q=0.8', offered, 'en'), 'de')
  assert.equal(negotiateLocale('en-GB;q=0.9, de;q=0.8', offered, 'en'), 'en')
  assert.equal(negotiateLocale('fr-FR,fr;q=0.9', offered, 'en'), 'en')
  assert.equal(negotiateLocale('fr;q=0.9, de;q=0.8', offered, 'en'), 'de')
  assert.equal(negotiateLocale(null, offered, 'de'), 'de')
  assert.equal(negotiateLocale('', offered, 'en'), 'en')
  assert.equal(negotiateLocale(';;;,,q=', offered, 'en'), 'en')
})

test('negotiation only ever answers something the product offers', () => {
  // A catalogue exists for German; this product has not offered it.
  assert.equal(negotiateLocale('de', ['en'], 'en'), 'en')
})

test('the cookie wins, but only when it names an offered locale', () => {
  const offered = ['en', 'de'] as const
  assert.equal(resolveLocale({ cookie: 'de', acceptLanguage: 'en' }, offered, 'en'), 'de')
  assert.equal(resolveLocale({ cookie: 'fr', acceptLanguage: 'de' }, offered, 'en'), 'de')
  assert.equal(resolveLocale({ cookie: 'de', acceptLanguage: 'de' }, ['en'], 'en'), 'en')
  assert.equal(resolveLocale({}, offered, 'en'), 'en')
})

test('the return path refuses anything that could leave the site', () => {
  assert.equal(safeReturnPath('/dashboard/settings'), '/dashboard/settings')
  assert.equal(safeReturnPath('/'), '/')
  assert.equal(safeReturnPath('//evil.example'), '/')
  assert.equal(safeReturnPath('/\\evil.example'), '/')
  assert.equal(safeReturnPath('https://evil.example'), '/')
  assert.equal(safeReturnPath('/a b'), '/')
  assert.equal(safeReturnPath('/a\r\nSet-Cookie: x'), '/')
  assert.equal(safeReturnPath(undefined), '/')
  assert.equal(safeReturnPath(42), '/')
})

test('direction and number formatting follow the locale', () => {
  assert.equal(localeDirection('en'), 'ltr')
  assert.equal(localeDirection('de'), 'ltr')
  assert.equal(formatNumber('de', 1234.5), '1.234,5')
  assert.equal(formatNumber('en', 1234.5), '1,234.5')
})
