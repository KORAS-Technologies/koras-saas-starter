import { expect, test } from '@playwright/test'
import { signInAs } from './support/session'

/**
 * The language, in a browser.
 *
 * The package tests prove the negotiation and the catalogues; the structural
 * tests in the starter prove every layout reads the locale. What neither can
 * prove is that pressing the button changes the document, that the document
 * says so in `lang`, and that the choice is still there on the next page --
 * those are claims about a cookie round-tripping through a real browser.
 *
 * Runs at both viewports like the shell suite. The public switcher is in the
 * footer at every width; signed in, Settings carries the form and the
 * appearance control, and the header carries neither.
 */

const MOBILE = 'mobile'

test('the public homepage follows the browser language until a choice is made', async ({
  browser,
}) => {
  const german = await browser.newContext({ locale: 'de-DE' })
  const page = await german.newPage()
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByRole('link', { name: 'Anmelden' }).first()).toBeVisible()
  await german.close()
})

test('a stranger can switch language on the sign-in page, and it sticks', async ({ page }) => {
  await page.goto('/login')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')

  // The switcher labels each language in itself, so this is "Deutsch" whatever
  // the page is currently in.
  await page.getByRole('button', { name: 'Deutsch' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByTestId('sign-in')).toHaveText('Anmelden')

  // A fresh document, no button pressed: the cookie is what carried it.
  await page.goto('/privacy')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Datenschutz')

  // The public footer carries the switcher at every width, so switching back
  // needs nothing opened first. The page is in German now; the button is not,
  // because every language is labelled in itself.
  await page.getByRole('contentinfo').getByRole('button', { name: 'English' }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
})

test('the signed-in shell is translated, sidebar and header alike', async ({ page, context }, testInfo) => {
  await signInAs(context)
  // Settings carries the language form and the appearance control at every
  // width; the header carries neither.
  await page.goto('/dashboard/settings')
  await expect(page.getByRole('radiogroup', { name: 'Appearance' })).toBeVisible()
  await page.getByLabel(/Show .* in/).selectOption('de')
  await page.getByRole('button', { name: 'Change language' }).click()
  await expect(page).toHaveURL(/\/dashboard\/settings$/)
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Einstellungen')
  // The appearance control is announced in German too: one locale, every string.
  await expect(page.getByRole('radiogroup', { name: 'Darstellung' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Kontomenü' })).toBeVisible()

  if (testInfo.project.name === MOBILE) {
    await page.getByRole('button', { name: 'Navigation öffnen' }).click()
  }
  await expect(page.locator('[aria-current="page"]:visible')).toContainText('Einstellungen')

  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Willkommen')
})

test('a locale the product does not offer is ignored, not honoured', async ({ page, request }) => {
  const response = await request.post('/api/locale', {
    form: { locale: 'fr', next: '/login' },
    maxRedirects: 0,
  })
  expect(response.status()).toBe(303)
  expect(response.headers()['set-cookie'] ?? '').not.toContain('koras-locale')

  await page.goto('/login')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
})

test('the return path cannot leave the site', async ({ request }) => {
  const response = await request.post('/api/locale', {
    form: { locale: 'de', next: '//evil.example/' },
    maxRedirects: 0,
  })
  expect(response.status()).toBe(303)
  const location = response.headers()['location'] ?? ''
  expect(new URL(location).pathname).toBe('/')
  expect(new URL(location).host).toBe(new URL(response.url()).host)
})
