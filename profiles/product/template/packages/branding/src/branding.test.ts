import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  NO_TENANT_BRANDING,
  brandingFor,
  defaultBranding,
  mergeBranding,
  parseTenantBranding,
  productConfig,
} from './index.js'

/**
 * What a customer may do to this product's stylesheet.
 *
 * `tenant_settings.branding` is a `jsonb` column a customer controls, and its
 * contents end up as CSS custom property values in a style attribute on every
 * page their staff load. A custom property value is not escaped the way text
 * content is, so this is the same category as browser input: a value the
 * product stored is not a value the product chose.
 *
 * These tests are the argument that the parser is the boundary. They live in
 * the generated product rather than in the starter because the code does.
 */

test('a colour must be a hex colour', () => {
  const { tokens } = parseTenantBranding({
    primaryColor: '#0f766e',
    secondaryColor: '#abc',
    accentColor: '#11223344',
  })
  assert.equal(tokens.primaryColor, '#0f766e')
  assert.equal(tokens.secondaryColor, '#abc')
  assert.equal(tokens.accentColor, '#11223344')
})

test('a colour that closes the declaration is dropped', () => {
  // The whole reason this parser exists. Accepted, this writes a rule of the
  // customer's choosing into every page of the product.
  const { tokens } = parseTenantBranding({
    primaryColor: 'red; } html { display: none } :root { --x: 1',
  })
  assert.equal(tokens.primaryColor, undefined)
})

test('a colour that fetches something is dropped', () => {
  for (const attack of [
    'url(https://evil.example/beacon)',
    'var(--brand-primary), url(x)',
    'expression(alert(1))',
    'rgb(0 0 0)',
  ]) {
    assert.equal(parseTenantBranding({ primaryColor: attack }).tokens.primaryColor, undefined, attack)
  }
})

test('a logo must be a same-origin path', () => {
  assert.equal(parseTenantBranding({ logoUrl: '/brand/acme.svg' }).tokens.logoUrl, '/brand/acme.svg')

  for (const attack of [
    // An SVG data URL is a document, and a document can carry script.
    'data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Pg==',
    // Protocol-relative: begins with a slash, resolves to another origin.
    '//evil.example/logo.svg',
    'https://evil.example/logo.svg',
    'javascript:alert(1)',
    '/logo.svg" onerror="alert(1)',
  ]) {
    assert.equal(parseTenantBranding({ logoUrl: attack }).tokens.logoUrl, undefined, attack)
  }
})

test('a radius must be a length', () => {
  assert.equal(parseTenantBranding({ radius: '0.5rem' }).tokens.radius, '0.5rem')
  assert.equal(parseTenantBranding({ radius: '4px' }).tokens.radius, '4px')
  assert.equal(parseTenantBranding({ radius: '0' }).tokens.radius, '0')
  assert.equal(parseTenantBranding({ radius: '9999vmax; }' }).tokens.radius, undefined)
})

test('a key nobody offered is not a token', () => {
  // Only TENANT_OVERRIDABLE is honoured. A customer cannot reach the semantic
  // text colours and make the product unreadable for their own staff.
  const { tokens } = parseTenantBranding({
    foregroundColor: '#ffffff',
    backgroundColor: '#ffffff',
    fontFamily: 'Comic Sans MS',
  })
  assert.deepEqual(tokens, {})
})

test('one bad value costs one token, not the whole brand', () => {
  const { tokens } = parseTenantBranding({
    primaryColor: '#0f766e',
    accentColor: 'not a colour',
  })
  assert.equal(tokens.primaryColor, '#0f766e')
  assert.equal(tokens.accentColor, undefined)
})

test('a malformed record degrades to the product’s own branding', () => {
  for (const raw of [null, undefined, 'string', 42, []]) {
    assert.deepEqual(parseTenantBranding(raw), NO_TENANT_BRANDING)
  }
})

test('a white-label name is bounded', () => {
  assert.equal(parseTenantBranding({ name: '  Acme Operations  ' }).name, 'Acme Operations')
  assert.equal(parseTenantBranding({ name: 'x'.repeat(500) }).name.length, 60)
  assert.equal(parseTenantBranding({ name: 42 }).name, '')
})

test('a customer overrides only what they set', () => {
  const tenant = parseTenantBranding({ primaryColor: '#0f766e' })
  const brand = brandingFor(productConfig.brand, tenant)
  assert.equal(brand.primaryColor, '#0f766e')
  // Everything else stays the product's, including the values a customer is
  // not allowed to reach.
  assert.equal(brand.foregroundColor, productConfig.brand.foregroundColor)
  assert.equal(brand.fontFamily, productConfig.brand.fontFamily)
})

test('no branding at all leaves the product exactly as configured', () => {
  assert.deepEqual(brandingFor(productConfig.brand, NO_TENANT_BRANDING), productConfig.brand)
})

test('mergeBranding still layers a product over the defaults', () => {
  const brand = mergeBranding(defaultBranding, { primaryColor: '#123456' })
  assert.equal(brand.primaryColor, '#123456')
  assert.equal(brand.radius, defaultBranding.radius)
})
