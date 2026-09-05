import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  marketingFor,
  navigationFor,
  productConfig,
  productFor,
  resolveNavigation,
} from './index.js'
import type { AccessContext, ProductConfig } from './index.js'

/**
 * The configuration, read in a language.
 *
 * `productConfig` is the one file a product edits, and these guard the two
 * promises the languages section makes about it: the default locale is one the
 * product offers, and a translation can be partial without leaving a hole.
 */

test('the default locale is one of the offered locales', () => {
  assert.ok(
    productConfig.i18n.locales.includes(productConfig.i18n.defaultLocale),
    `defaultLocale "${productConfig.i18n.defaultLocale}" is not in locales`,
  )
})

test('every translated locale is one the product offers', () => {
  for (const locale of Object.keys(productConfig.translations)) {
    assert.ok(
      (productConfig.i18n.locales as readonly string[]).includes(locale),
      `translations.${locale} exists but "${locale}" is not offered`,
    )
  }
})

test('the default locale reads the configuration unchanged', () => {
  const locale = productConfig.i18n.defaultLocale
  assert.equal(marketingFor(locale), productConfig.marketing)
  assert.equal(productFor(locale), productConfig.product)
  assert.equal(navigationFor(locale), productConfig.navigation)
})

test('a translated list keeps the shape of the default', () => {
  // A German feature grid with a different number of cards, or a link to a
  // different route, is a translation that changed the page rather than its
  // words. Lists must match in length; links must match in href.
  const base = productConfig.marketing
  for (const locale of productConfig.i18n.locales) {
    const translated = marketingFor(locale)
    for (const list of ['nav', 'values', 'features', 'outcomes', 'steps', 'trust', 'footerGroups'] as const) {
      assert.equal(translated[list].length, base[list].length, `${locale}: ${list} changed length`)
    }
    assert.deepEqual(
      translated.nav.map((link) => link.href),
      base.nav.map((link) => link.href),
      `${locale}: nav links point somewhere else`,
    )
    assert.deepEqual(
      translated.footerGroups.map((group) => group.links.map((link) => link.href)),
      base.footerGroups.map((group) => group.links.map((link) => link.href)),
      `${locale}: footer links point somewhere else`,
    )
    assert.deepEqual(
      translated.features.map((feature) => feature.icon),
      base.features.map((feature) => feature.icon),
      `${locale}: feature icons changed`,
    )
  }
})

test('a partial translation falls back field by field', () => {
  const config: ProductConfig = {
    ...productConfig,
    i18n: { defaultLocale: 'en', locales: ['en', 'de'] },
    translations: { de: { marketing: { heroTitle: 'Hallo' }, product: { tagline: 'Servus' } } },
  }
  const marketing = marketingFor('de', config)
  assert.equal(marketing.heroTitle, 'Hallo')
  assert.equal(marketing.heroDescription, productConfig.marketing.heroDescription)

  const product = productFor('de', config)
  assert.equal(product.tagline, 'Servus')
  assert.equal(product.description, productConfig.product.description)
  assert.equal(product.name, productConfig.product.name)

  // No navigation translation at all: the registry comes back as it is.
  assert.equal(navigationFor('de', config), productConfig.navigation)
})

test('navigation labels translate by id and nothing else moves', () => {
  const german = navigationFor('de')
  const ids = (config: typeof german) => config.modules.map((module) => module.id)
  assert.deepEqual(ids(german), ids(productConfig.navigation))

  for (const [index, module] of german.modules.entries()) {
    const original = productConfig.navigation.modules[index]!
    assert.equal(module.href, original.href)
    assert.deepEqual(module.requiredPermissions, original.requiredPermissions)
    assert.deepEqual(module.requiredEntitlements, original.requiredEntitlements)
  }

  const home = german.modules.find((module) => module.id === 'home')
  assert.equal(home?.label, 'Start')
  const administration = german.groups.find((group) => group.id === 'administration')
  assert.equal(administration?.label, 'Verwaltung')
})

test('a translated registry resolves to the same modules as the default', () => {
  const context: AccessContext = {
    access: { granted: true, role: 'product_admin', permissions: ['settings.read', 'team.read'] },
    capabilities: productConfig.product.capabilities,
    entitlements: { resolved: true, plan: 'starter', features: {} },
    features: {},
    organizationRoles: ['organization_admin'],
  }
  const english = resolveNavigation(productConfig.navigation, context)
  const german = resolveNavigation(navigationFor('de'), context)

  const shape = (groups: typeof english) =>
    groups.map((group) => ({
      id: group.id,
      items: group.items.map((item) => ({ id: item.id, href: item.href, state: item.state, lockedBy: item.lockedBy })),
    }))
  assert.deepEqual(shape(german), shape(english))

  // The locked reason is carried as a gate name, which is what the shell
  // translates. The English sentence is still there for whoever reads it.
  const reports = english.flatMap((group) => group.items).find((item) => item.id === 'reports')
  assert.equal(reports?.state, 'locked')
  assert.equal(reports?.lockedBy, 'entitlement')
  assert.equal(reports?.lockedReason, 'Not included in your plan')
})
