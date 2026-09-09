import { expect, test } from '@playwright/test'

/**
 * The page the welcome email lands on, without a Control Plane behind it.
 *
 * What can be proved here is the page's own behaviour: it is public, it says
 * one thing for every bad link, and the form is the product's. Spending a real
 * link needs the platform, which the generated project's suite does not have;
 * that half is `tests/integration/test_owner_activation.py` in the Control
 * Plane.
 */

test('the activation page is public and refuses a link with no token', async ({ page }) => {
  const response = await page.goto('/activate')
  expect(response?.status()).toBe(200)
  await expect(page).not.toHaveURL(/\/login\?next=/)
  await expect(page.getByTestId('activate-incomplete')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
})

test('a link the platform does not know is one message, not three', async ({ page }) => {
  // No Control Plane is configured in this suite, so every token is unknown.
  // The page must not say "expired" or "used" -- those would be claims about a
  // token it knows nothing about.
  await page.goto('/activate?token=not-a-real-token')
  const failed = page.getByTestId('activate-failed')
  await expect(failed).toBeVisible()
  await expect(failed).toContainText('not valid')
  await expect(page.getByTestId('activate-form')).toHaveCount(0)
})

test('the failure is translated, with the same property', async ({ browser }) => {
  const german = await browser.newContext({ locale: 'de-DE' })
  const page = await german.newPage()
  await page.goto('/activate?token=not-a-real-token')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByTestId('activate-failed')).toContainText('nicht gültig')
  await german.close()
})
