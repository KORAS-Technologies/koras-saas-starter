import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { templatePath } from './template-path'

/**
 * The owner's first password is set on the product's page, not ZITADEL's.
 *
 * Control Plane R-107: until 2026-09-09 the owner of a new organization got
 * ZITADEL's own "Initialize User" mail, set their password on ZITADEL's screen
 * and was left in the ZITADEL Console -- every surface SECURITY_MODEL §8
 * forbids. The Control Plane now sends the welcome with a link to `/activate`
 * on the product, and this page is that link's other half.
 *
 * Structural, like the signup tests beside it: the page is a template, and
 * what matters is that the pieces are wired -- public, one message for every
 * bad link, the password compared on the server, nothing echoed.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const ACTIVATE = join(PRODUCT, 'apps', 'web', 'src', 'app', 'activate')

function read(...segments: string[]): string {
  return readFileSync(join(...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the activation page', () => {
  it('exists, with a page, a form, its action and its state', () => {
    for (const file of ['page.tsx.hbs', 'ActivateForm.tsx.hbs', 'actions.ts.hbs', 'state.ts']) {
      expect(existsSync(join(ACTIVATE, file)), file).toBe(true)
    }
  })

  it('is public: nobody who arrives has a password yet', () => {
    const middleware = read(PRODUCT, 'apps', 'web', 'src', 'middleware.ts.hbs')
    const declaration = /const PUBLIC_PATHS = \[([^\]]*)\]/.exec(middleware)?.[1] ?? ''
    expect(declaration).toContain("'/activate'")
  })

  it('spends the token on the server and posts the password to the platform', () => {
    const actions = read(ACTIVATE, 'actions.ts.hbs')
    expect(actions.startsWith("'use server'")).toBe(true)
    expect(actions).toContain('/api/signup/v1/activations/')
    expect(actions).toContain("method: 'POST'")
    expect(actions).toContain('JSON.stringify({ password })')
    // The token never reaches a browser bundle as an environment variable.
    expect(actions).toContain('process.env.KORAS_CONTROL_PLANE_URL')
    expect(actions).not.toContain('NEXT_PUBLIC_')
  })

  it('compares the two fields where it counts', () => {
    const actions = read(ACTIVATE, 'actions.ts.hbs')
    expect(actions).toContain('password !== confirm')
    expect(actions).toContain("field: 'confirm'")
    expect(actions).toContain('password.length < 8')
  })

  it('says one thing for every bad link', () => {
    // Unknown, expired and spent are one outcome, as on /signup/verify.
    const actions = read(ACTIVATE, 'actions.ts.hbs')
    const code = actions.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '')
    expect(code).not.toMatch(/expired|already used/i)
    const page = read(ACTIVATE, 'page.tsx.hbs')
    expect(page).toContain("outcome.status === 'invalid'")
    expect(page).toContain('activate.invalid.title')
    expect(page).not.toContain('activate.expired')
  })

  it('takes the password as a password, and never echoes it', () => {
    const form = read(ACTIVATE, 'ActivateForm.tsx.hbs')
    expect(form.match(/type="password"/g)?.length).toBe(2)
    expect(form).toContain('autoComplete="new-password"')
    expect(form).not.toContain('defaultValue')
    expect(form).toContain('<input type="hidden" name="token"')
  })

  it('sends the person to sign in when the password is set, and not before', () => {
    const form = read(ACTIVATE, 'ActivateForm.tsx.hbs')
    expect(form).toContain("state.status === 'ok'")
    expect(form).toContain('href="/login"')
    expect(form).not.toContain('redirect(')
  })

  it('is translated in every catalogue', () => {
    const en = read(PRODUCT, 'packages', 'i18n', 'src', 'messages', 'en.ts')
    const keys = [...en.matchAll(/'(activate\.[a-zA-Z.]+)':/g)].map((m) => m[1] as string)
    expect(keys.length).toBeGreaterThanOrEqual(18)
    for (const locale of ['de', 'es']) {
      const catalogue = read(PRODUCT, 'packages', 'i18n', 'src', 'messages', `${locale}.ts`)
      for (const key of keys) expect(catalogue, `${locale} lacks ${key}`).toContain(`'${key}':`)
    }
  })

  it('has a browser test, run against the generated project', () => {
    expect(existsSync(join(PRODUCT, 'e2e', 'activate.spec.ts.hbs'))).toBe(true)
  })
})
