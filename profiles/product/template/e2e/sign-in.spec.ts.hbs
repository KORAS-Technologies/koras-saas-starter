import { expect, test } from '@playwright/test'

/**
 * The sign-in page in both its shapes, without a Control Plane behind it.
 *
 * What can be proved here is the page's own behaviour: that it is still the
 * button until the identity provider sends somebody back with an auth
 * request; that with one it is a form on this product's page with labelled
 * fields and a way to a forgotten password; and that a platform that cannot be
 * reached is one message, not a stack trace. Checking a real password needs
 * the platform and ZITADEL, which this suite does not have; that half is
 * `tests/integration/test_product_sign_in.py` in the Control Plane.
 */

test('without an auth request, and no provider configured, the page is the button', async ({
  page,
}) => {
  // With a provider configured the page redirects into the sign-in at once;
  // this suite has none, so it sees the fallback the redirect would have
  // replaced, and asserts that the fallback still starts the same flow.
  await page.goto('/login')
  const button = page.getByTestId('sign-in')
  await expect(button).toBeVisible()
  await expect(button).toHaveAttribute('href', /^\/api\/auth\/start\?next=/)
  await expect(page.getByTestId('sign-in-form')).toHaveCount(0)
})

test('a sign-out lands on a signed-out page, not in the provider', async ({ page }) => {
  // The sign-out is a form post, and the content security policy's
  // form-action is 'self': a redirect chain from that post into the provider
  // would be refused by the browser. So the page after a sign-out is a page.
  await page.goto('/login?signed_out=1')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('signed out')
  await expect(page.getByTestId('sign-in')).toBeVisible()
})

test('with an auth request the page is the sign-in itself', async ({ page }) => {
  await page.goto('/login?authRequest=V2_test')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Sign in')
  const form = page.getByTestId('sign-in-form')
  await expect(form).toBeVisible()
  await expect(page.getByTestId('sign-in')).toHaveCount(0)

  // Labelled, and the labels are real associations rather than placeholders.
  const email = page.getByLabel('Email address')
  const password = page.getByLabel('Password', { exact: true })
  await expect(email).toHaveAttribute('type', 'email')
  await expect(email).toHaveAttribute('autocomplete', 'username')
  await expect(password).toHaveAttribute('type', 'password')
  await expect(password).toHaveAttribute('autocomplete', 'current-password')
  await expect(email).toBeFocused()

  // The way out for a forgotten password is on the form, not behind a search.
  await expect(page.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute(
    'href',
    '/login/forgot',
  )
})

test('with no platform there is no provider button, and the password form stands alone', async ({
  page,
}) => {
  // "Continue with Google" is drawn from what the platform says the instance
  // offers. No platform, no list, no button -- and never a button that would
  // lead nowhere.
  await page.goto('/login?authRequest=V2_test')
  await expect(page.getByTestId('sign-in-form')).toBeVisible()
  await expect(page.getByTestId('sign-in-providers')).toHaveCount(0)
})

test('a provider that sent the person back without a proof is an expired sign-in', async ({
  page,
}) => {
  // The return page needs the intent's id and token in the URL. Without
  // them there is nothing to finish, and the only way on is to start again.
  await page.goto('/login/provider?authRequest=V2_test')
  const expired = page.getByTestId('sign-in-expired')
  await expect(expired).toBeVisible()
  await expect(expired.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/login')
})

test('a provider return the platform cannot finish is one message, with the password form', async ({
  page,
}) => {
  // No Control Plane here. The refusal must not claim anything about the
  // person -- nothing checked them -- and the password form stays, because
  // that is the other way in.
  await page.goto('/login/provider?authRequest=V2_test&id=intent-1&token=proof')
  const error = page.getByTestId('sign-in-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('not available')
  await expect(page.getByTestId('sign-in-form')).toBeVisible()
  await expect(page.getByLabel('Email address')).toBeVisible()
})

test('a provider the person came back from without finishing is said once', async ({ page }) => {
  await page.goto('/login?authRequest=V2_test&provider=failed')
  const error = page.getByTestId('sign-in-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('did not finish')
  await expect(page.getByTestId('sign-in-form')).toBeVisible()
})

test('a platform that cannot be reached is one message, under the form', async ({ page }) => {
  // No Control Plane is configured in this suite. The refusal must not claim
  // the password was wrong -- nothing checked it -- and must leave the form
  // in place with what was typed still there to retry.
  await page.goto('/login?authRequest=V2_test')
  await page.getByLabel('Email address').fill('owner@example.com')
  await page.getByLabel('Password', { exact: true }).fill('correct horse battery')
  await page.getByTestId('sign-in-submit').click()

  const error = page.getByTestId('sign-in-error')
  await expect(error).toBeVisible()
  await expect(error).toHaveAttribute('role', 'alert')
  await expect(error).toContainText('not available')
  await expect(error).not.toContainText('wrong')
  await expect(page.getByTestId('sign-in-form')).toBeVisible()
})

test('the form is usable from the keyboard alone', async ({ page }) => {
  await page.goto('/login?authRequest=V2_test')
  await expect(page.getByLabel('Email address')).toBeFocused()
  await page.keyboard.type('owner@example.com')
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused()
  await page.keyboard.type('correct horse battery')
  await page.keyboard.press('Tab')
  await expect(page.getByTestId('sign-in-submit')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('sign-in-error')).toBeVisible()
})

test('the sign-in form is translated', async ({ browser }) => {
  const german = await browser.newContext({ locale: 'de-DE' })
  const page = await german.newPage()
  await page.goto('/login?authRequest=V2_test')
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await expect(page.getByLabel('E-Mail-Adresse')).toBeVisible()
  await expect(page.getByTestId('sign-in-submit')).toHaveText('Anmelden')
  await german.close()
})

test('a forgotten password is asked for on this product, and answered once', async ({
  page,
}) => {
  const response = await page.goto('/login/forgot')
  expect(response?.status()).toBe(200)
  await expect(page).not.toHaveURL(/\/login\?next=/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Reset your password')

  const email = page.getByLabel('Email address')
  await expect(email).toBeFocused()
  await email.fill('owner@example.com')
  await page.getByTestId('forgot-submit').click()

  // No platform here, so the honest answer is that it is not available --
  // never "no account with that address", which nothing here can know.
  const error = page.getByTestId('forgot-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('not available')
  await expect(page.getByRole('link', { name: 'Back to sign in' })).toHaveAttribute('href', '/login')
})

test('the forgotten-password page is translated', async ({ browser }) => {
  const spanish = await browser.newContext({ locale: 'es-ES' })
  const page = await spanish.newPage()
  await page.goto('/login/forgot')
  await expect(page.locator('html')).toHaveAttribute('lang', 'es')
  await expect(page.getByLabel('Dirección de correo electrónico')).toBeVisible()
  await spanish.close()
})
