import { expect, test } from '@playwright/test'
import { signInAs } from './support/session'

/**
 * The authenticated shell, in a browser.
 *
 * Each test below asserts something the server-side probe could not: it can see
 * that a toggle carries `aria-controls`, and it cannot see whether pressing
 * Escape gives the focus back. Those are the claims the shell's own
 * documentation makes about itself, and until this suite existed they were
 * claims and nothing more.
 *
 * The two projects in `playwright.config.ts` run this file at 375 and 1440,
 * because below `lg` the navigation is a drawer and above it a sidebar. A test
 * that skipped one would leave half the navigation unexercised, which is how
 * the drawer came to be the untested half in the first place.
 */

const MOBILE = 'mobile'

test.beforeEach(async ({ context }) => {
  await signInAs(context)
})

test('the signed-in shell renders one main landmark and lands on it', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page.locator('#main-content')).toHaveCount(1)
  // The skip link is the first thing a keyboard reaches, and it has to point at
  // something. A skip link to a missing target is worse than none: it silently
  // does nothing and looks like the page swallowed the key.
  await page.keyboard.press('Tab')
  const skip = page.locator(':focus')
  await expect(skip).toHaveAttribute('href', '#main-content')
})

test('the current page is announced exactly once, wherever the navigation is', async ({
  page,
}, testInfo) => {
  await page.goto('/dashboard')
  // `:visible`, and the qualifier is the finding. The shell renders the
  // navigation twice — once in the sidebar and once inside the drawer, which
  // stays in the DOM while closed so the toggle's `aria-controls` points at
  // something real. Two elements carry `aria-current="page"` at every viewport
  // and at most one is reachable. A DOM count says two; the accessibility tree
  // is what the claim is about, and only a browser can tell them apart.
  const current = page.locator('[aria-current="page"]:visible')

  if (testInfo.project.name === MOBILE) {
    // Below `lg` no navigation is on screen at all until the drawer is opened.
    // That is the design rather than a gap — and it means "the current page is
    // announced" is a claim about the drawer at this width, not about the page.
    await expect(current).toHaveCount(0)
    await page.getByRole('button', { name: 'Open navigation' }).click()
  }

  await expect(current).toHaveCount(1)
  await expect(current).toContainText('Home')
})

test('a nested page highlights one entry, not its whole ancestry', async ({
  page,
}, testInfo) => {
  await page.goto('/dashboard/settings/team')
  const nav = page.locator('[aria-current="page"]:visible')

  if (testInfo.project.name === MOBILE) {
    await page.getByRole('button', { name: 'Open navigation' }).click()
  }

  // `Team & Access` and `Settings` are siblings in one flat list, and
  // `/dashboard/settings` is a prefix of `/dashboard/settings/team`. The
  // sidebar used to light up both and call it a breadcrumb: two highlights in a
  // list with no visible nesting read as two selected pages, and the highlight
  // disagreed with `aria-current`, which was on the exact match alone.
  //
  // One rule now decides both, and it is the rule the route gate uses: the
  // longest match owns the URL.
  await expect(nav).toHaveCount(1)
  await expect(nav).toContainText('Team & Access')
})

test('a plan-gated module is offered, not merely missing', async ({ page }, testInfo) => {
  await page.goto('/dashboard')
  if (testInfo.project.name === MOBILE) {
    await page.getByRole('button', { name: 'Open navigation' }).click()
  }

  // No entitlements resolve in this suite -- no Control Plane runs -- so both
  // plan gates are closed, and the two behaviours are visible side by side.
  //
  // `Reports` locks: present, disabled, and its accessible name carries the
  // reason, because collapsed that name is the only thing distinguishing it
  // from an available icon.
  const reports = page.getByRole('button', { name: /Reports/ })
  await expect(reports).toBeVisible()
  await expect(reports).toBeDisabled()

  // `Insights` hides: absent entirely. Asserting the absence is the point --
  // "hidden" and "never added to the registry" look identical on a screenshot.
  await expect(page.getByRole('link', { name: 'Insights' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Insights/ })).toHaveCount(0)
})

test.describe('the drawer', () => {
  // Skipped per test rather than per describe: the condition is the project's
  // viewport, and the boolean form is the one the runner types. A callback
  // taking `testInfo` at describe level compiles only by inference and would be
  // the second untypechecked thing in an e2e directory.
  test('opens from the toggle and traps the keyboard inside it', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== MOBILE, 'below lg only')
    await page.goto('/dashboard')
    const toggle = page.getByRole('button', { name: 'Open navigation' })
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await toggle.click()
    const drawer = page.getByRole('dialog', { name: 'Product navigation' })
    await expect(drawer).toBeVisible()

    // Focus starts inside rather than on the body. Without this the next Tab
    // begins the page again, behind the panel covering it.
    await expect(drawer.locator(':focus')).toHaveCount(1)

    // Walk far enough to leave any panel that is not trapping, then assert we
    // are still inside. Counting the focusables and tabbing exactly that many
    // times would pass on a panel with one link and no trap at all.
    for (let index = 0; index < 20; index += 1) {
      await page.keyboard.press('Tab')
      expect(await drawer.locator(':focus').count()).toBe(1)
    }
  })

  test('Escape closes it and gives the focus back to the toggle', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== MOBILE, 'below lg only')
    await page.goto('/dashboard')
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await expect(page.getByRole('dialog', { name: 'Product navigation' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: 'Product navigation' })).toBeHidden()
    // Not merely closed: the focus has to come back somewhere useful. Left on
    // the body, the next Tab starts the page over, which is the failure mode
    // that makes a drawer unusable without a pointer.
    await expect(page.locator(':focus')).toHaveAccessibleName('Open navigation')
  })

  test('closes when a navigation happens, rather than covering the new page', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== MOBILE, 'below lg only')
    await page.goto('/dashboard')
    await page.getByRole('button', { name: 'Open navigation' }).click()
    const drawer = page.getByRole('dialog', { name: 'Product navigation' })
    await expect(drawer).toBeVisible()

    await drawer.getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/dashboard\/settings$/)
    await expect(drawer).toBeHidden()
  })
})

test.describe('the sidebar', () => {
  test('collapses, and every link keeps its accessible name', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === MOBILE, 'lg and above only')
    await page.goto('/dashboard')
    const nav = page.getByRole('navigation', { name: 'Product' })
    const before = await nav.getByRole('link').allTextContents()
    expect(before.length).toBeGreaterThan(0)

    const collapse = page.getByRole('button', { name: 'Collapse the sidebar' })
    await expect(collapse).toHaveAttribute('aria-pressed', 'false')
    await collapse.click()
    await expect(page.getByRole('button', { name: 'Expand the sidebar' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    // The labels go visually hidden, not away. An icon-only link with no
    // accessible name announces its own URL, which is the whole reason the
    // collapsed state renders `sr-only` text instead of dropping it.
    for (const label of before) {
      await expect(nav.getByRole('link', { name: label.trim(), exact: true })).toHaveCount(1)
    }
  })

  test('the preference survives a navigation', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === MOBILE, 'lg and above only')
    await page.goto('/dashboard')
    await page.getByRole('button', { name: 'Collapse the sidebar' }).click()
    await page.getByRole('navigation', { name: 'Product' }).getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/dashboard\/settings$/)
    // Read back from localStorage through the rendered control, not from
    // storage directly: what matters is that the shell applied it, and a test
    // asserting the stored string would pass with the preference ignored.
    await expect(page.getByRole('button', { name: 'Expand the sidebar' })).toBeVisible()
  })
})

test('a caller with no session is sent to sign in, not shown the shell', async ({ browser }) => {
  // A fresh context, so this one is genuinely signed out rather than relying on
  // a cookie having been cleared.
  const anonymous = await browser.newContext()
  const page = await anonymous.newPage()
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('#main-content')).toHaveCount(1)
  await anonymous.close()
})
