import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  NO_TENANT_BRANDING,
  brandingFor,
  defaultBranding,
  mergeBranding,
  mergeTenantBranding,
  parsePlatformBranding,
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

test('a corner style is one of two names, and nothing else is', () => {
  assert.equal(parseTenantBranding({ cornerStyle: 'flat' }).cornerStyle, 'flat')
  assert.equal(parseTenantBranding({ cornerStyle: 'rounded' }).cornerStyle, 'rounded')

  // This column used to accept a CSS length, guarded by a regular expression
  // that had to be right about `9999vmax; }`. Two names cannot be malformed, so
  // the guard is the type rather than a pattern -- and every one of these,
  // including the lengths that used to be valid, now leaves the product's own
  // radius standing.
  for (const attack of ['0.5rem', '4px', '0', '9999vmax; }', 'Rounded', '', null, 7, {}]) {
    assert.equal(parseTenantBranding({ cornerStyle: attack }).cornerStyle, null, String(attack))
  }
})

test('a corner style becomes a radius, and only at the end', () => {
  // The customer picks a look; `brandingFor` is where a look becomes a length.
  // Nothing downstream of it knows the choice existed, which is what keeps the
  // token pipeline unaware of tenants.
  const flat = brandingFor(productConfig.brand, {
    tokens: {},
    name: '',
    cornerStyle: 'flat',
  })
  assert.equal(flat.radius, '0')

  const rounded = brandingFor(productConfig.brand, {
    tokens: {},
    name: '',
    cornerStyle: 'rounded',
  })
  assert.equal(rounded.radius, '0.75rem')
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

/**
 * The Control Plane's answer, in the Control Plane's names.
 *
 * `parsePlatformBranding` reads `GET /api/portal/v1/products/{code}/branding`,
 * whose fields are the platform's -- `primary_color`, `company_name`,
 * `corner_style`. They are asserted here for the reason the entitlement field
 * names are: a rename on either side is otherwise a silent no-op, every key
 * unknown and every value dropped, and the customer simply appears to have set
 * nothing. That is what white labelling looked like before this parser existed.
 */

const PLATFORM_ANSWER = {
  product_code: 'example',
  company_name: 'Acme Corporation',
  logo_light: 'https://assets.platform.example/acme/light.svg',
  logo_dark: 'https://assets.platform.example/acme/dark.svg',
  primary_color: '#dcf6ff',
  secondary_color: '#0f766e',
  accent_color: '#f97316',
  heading_font: 'Inter',
  body_font: 'Inter',
  corner_style: 'flat',
}

test('the platform’s answer is read in the platform’s names', () => {
  const branding = parsePlatformBranding(PLATFORM_ANSWER)
  assert.equal(branding.tokens.primaryColor, '#dcf6ff')
  assert.equal(branding.tokens.secondaryColor, '#0f766e')
  assert.equal(branding.tokens.accentColor, '#f97316')
  assert.equal(branding.name, 'Acme Corporation')
  assert.equal(branding.cornerStyle, 'flat')
})

test('this package’s own names mean nothing to the platform parser', () => {
  // The defect this guards against is the two sources being fed to each
  // other's parser. Neither spelling may be honoured by the wrong one.
  assert.deepEqual(
    parsePlatformBranding({ primaryColor: '#dcf6ff', name: 'Acme', cornerStyle: 'flat' }),
    NO_TENANT_BRANDING,
  )
  assert.deepEqual(
    parseTenantBranding({ primary_color: '#dcf6ff', company_name: 'Acme', corner_style: 'flat' }),
    NO_TENANT_BRANDING,
  )
})

test('the platform’s images are not rendered, and the fonts are not reachable', () => {
  // Remote `https` assets are refused by this product's `img-src 'self'`, so
  // honouring them would put a broken image in the header. Fonts are not a
  // customer's to set here any more than they are through the local column.
  const { tokens } = parsePlatformBranding(PLATFORM_ANSWER)
  assert.equal(tokens.logoUrl, undefined)
  assert.equal(tokens.logoDarkUrl, undefined)
  assert.deepEqual(Object.keys(tokens).sort(), ['accentColor', 'primaryColor', 'secondaryColor'])
})

test('the platform parser applies the same colour rule', () => {
  assert.equal(
    parsePlatformBranding({ primary_color: 'red; } html { display: none }' }).tokens.primaryColor,
    undefined,
  )
  assert.equal(parsePlatformBranding({ corner_style: '4px' }).cornerStyle, null)
  assert.equal(parsePlatformBranding({ company_name: 'x'.repeat(500) }).name.length, 60)
})

test('an empty platform record is the product’s own branding', () => {
  // The portal answers a record of nulls for a customer who has set nothing,
  // not a 404 -- and nulls set nothing.
  assert.deepEqual(
    parsePlatformBranding({ product_code: 'example', primary_color: null, corner_style: null }),
    NO_TENANT_BRANDING,
  )
  for (const raw of [null, undefined, 'string', 42, []]) {
    assert.deepEqual(parsePlatformBranding(raw), NO_TENANT_BRANDING)
  }
})

test('the platform’s branding is layered over the local column', () => {
  const local = parseTenantBranding({
    primaryColor: '#111111',
    accentColor: '#222222',
    name: 'Local',
    cornerStyle: 'rounded',
  })
  const platform = parsePlatformBranding({ primary_color: '#dcf6ff', company_name: 'Acme' })

  const merged = mergeTenantBranding(local, platform)
  // The platform wins where both speak.
  assert.equal(merged.tokens.primaryColor, '#dcf6ff')
  assert.equal(merged.name, 'Acme')
  // What only the local column set still stands.
  assert.equal(merged.tokens.accentColor, '#222222')
  assert.equal(merged.cornerStyle, 'rounded')
  // And nothing anywhere is still nothing.
  assert.deepEqual(mergeTenantBranding(NO_TENANT_BRANDING, NO_TENANT_BRANDING), NO_TENANT_BRANDING)
})
