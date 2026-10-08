import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { signInAs } from './support/session'

/**
 * The current item in the navigation is readable, with room to spare (GR-380).
 *
 * The sidebar marked the current page with the brand colour on a 10% tint of itself. For the
 * default blue that is 4.48:1 in the light palette and 3.07:1 in the dark one, and the brand
 * colour is a tenant's to change, so no fixed figure could have been right for every product.
 * The label is now the page's own text colour on the tint; the brand is carried by a bar and the
 * icon, which are graphics.
 *
 * Measured here rather than by an accessibility engine, so a product that has none still has the
 * claim: the label's colour against what is actually painted behind it, found by drawing the
 * element's ancestors' backgrounds onto a canvas in order (which composites the tint exactly as
 * the browser does, whatever colour space the stylesheet wrote it in). WCAG 2 relative luminance.
 *
 * The margin is asked for, not just the floor: AA is 4.5:1, and a pass at 4.51 is one theme
 * tweak from a failure.
 *
 * `desktop` runs this against the sidebar and `mobile` against the drawer, in the light and the
 * dark palette, and once through the Appearance control as well as through the machine's setting.
 */

/** AAA for body text. The floor is 4.5:1; this is the margin asked for above it. */
const MARGIN = 7

test.beforeEach(async ({ context }) => {
  await signInAs(context)
})

async function openNavigationIfDrawer(page: Page, projectName: string): Promise<void> {
  if (projectName !== 'mobile') return
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(page.getByRole('dialog', { name: 'Product navigation' })).toBeVisible()
}

/** The contrast of the visible current item's label against what is painted behind it. */
async function currentItemContrast(page: Page): Promise<number> {
  const current = page.locator('[aria-current="page"]:visible')
  await expect(current).toHaveCount(1)
  return current.evaluate((link) => {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (ctx === null) throw new Error('no canvas to measure with')
    const pixel = (): [number, number, number] => {
      const data = ctx.getImageData(0, 0, 1, 1).data
      return [data[0], data[1], data[2]]
    }
    // What is behind the label: every ancestor's background, outermost first, composited in order.
    const chain: Element[] = []
    for (let node: Element | null = link; node !== null; node = node.parentElement) chain.unshift(node)
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, 1, 1)
    for (const node of chain) {
      ctx.fillStyle = getComputedStyle(node).backgroundColor
      ctx.fillRect(0, 0, 1, 1)
    }
    const behind = pixel()
    // The label's own colour, normalised to sRGB by the same canvas.
    ctx.clearRect(0, 0, 1, 1)
    ctx.fillStyle = getComputedStyle(link).color
    ctx.fillRect(0, 0, 1, 1)
    const text = pixel()
    const luminance = ([r, g, b]: [number, number, number]) => {
      const channel = (value: number) => {
        const s = value / 255
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }
    const [lighter, darker] = [luminance(text), luminance(behind)].sort((a, b) => b - a)
    return (lighter + 0.05) / (darker + 0.05)
  })
}

for (const scheme of ['light', 'dark'] as const) {
  test(`the current navigation item clears AA with a margin in the ${scheme} palette`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme: scheme })
    await page.goto('/dashboard')
    await openNavigationIfDrawer(page, testInfo.project.name)
    const ratio = await currentItemContrast(page)
    expect(ratio, `${scheme} contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(MARGIN)
  })
}

test('the Appearance control reaches the same result as the machine setting', async ({ page }, testInfo) => {
  await page.goto('/dashboard/settings')
  await page.getByRole('radio', { name: 'Dark' }).click()
  await expect(page.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
  await page.goto('/dashboard')
  await openNavigationIfDrawer(page, testInfo.project.name)
  const ratio = await currentItemContrast(page)
  expect(ratio, `explicit dark contrast ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(MARGIN)
})

test('the brand is still shown on the current item: a bar and the icon, not the label', async ({ page }, testInfo) => {
  await page.goto('/dashboard')
  await openNavigationIfDrawer(page, testInfo.project.name)
  const current = page.locator('[aria-current="page"]:visible')
  await expect(current).toHaveCount(1)
  const bar = await current.evaluate((link) => {
    const style = getComputedStyle(link, '::before')
    return { width: style.width, background: style.backgroundColor }
  })
  expect(bar.width).toBe('4px')
  expect(bar.background).not.toBe('rgba(0, 0, 0, 0)')
  // The label is the page's text colour, which is what makes its contrast independent of the brand.
  const [label, body] = await Promise.all([
    current.evaluate((link) => getComputedStyle(link).color),
    page.evaluate(() => getComputedStyle(document.body).color),
  ])
  expect(label).toBe(body)
})
