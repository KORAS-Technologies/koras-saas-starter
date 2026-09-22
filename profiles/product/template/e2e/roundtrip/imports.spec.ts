import { expect, test } from '@playwright/test'
import { signInAs } from '../support/session'

/**
 * The import page, rendered.
 *
 * **Nothing in this estate had ever drawn this surface.** `ImportPanel` returns
 * its no-targets banner and stops when a product declares no targets, and a
 * generated product declares none — correctly, because a target names a table
 * the product owns and the starter owns no domain. So `e2e/imports.spec.ts`
 * asserts that banner, and everything past it — the picker, the mapping, the
 * result card, the report, the confirm control — was protected by assertions
 * that read template text and by nothing else.
 *
 * That is how Phase 2 shipped a commit path that could not succeed once, and a
 * problem report a customer could not reach after a reload. Both were found by
 * a person opening the page. `docs/features/data-import/phase-2-review.md` in
 * the starter is the record.
 *
 * ## Why this skips by default
 *
 * It needs a declared target, and the one it uses is a fixture that
 * `Generator Integration` writes into the generated project for the length of
 * one run — `.github/fixtures/import-target.py` in the starter, which is inside
 * no template and therefore in no product. `E2E_IMPORT_FIXTURE` is how that
 * workflow says it installed it.
 *
 * A product that declares targets of its own can set the variable and adapt the
 * first assertion; everything below it reads the page rather than the fixture.
 */

const RUN_ID = '44444444-4444-4444-8444-444444444444'

test.skip(
  !process.env.E2E_IMPORT_FIXTURE,
  'needs a declared import target; Generator Integration installs the fixture',
)

test('the page renders what the registry holds', async ({ page, context }) => {
  await signInAs(context, { roles: ['organization_admin'], subject: 'e2e-subject' })
  await page.goto('/dashboard/imports')

  // The panel rather than the no-targets banner. This is the assertion no run
  // in this estate could make before the fixture existed.
  await expect(page.getByTestId('imports-panel')).toBeVisible()

  const picker = page.getByRole('combobox', { name: 'What to import' })
  await expect(picker).toBeVisible()
  expect((await picker.locator('option').allTextContents()).join(' ')).toContain(
    'fixture.contacts',
  )

  // Both declared operations, from the target rather than from a list the page
  // keeps. One option would render a control that cannot be wrong.
  const operations = page.getByRole('combobox', { name: 'Existing records' })
  expect((await operations.locator('option').allTextContents()).length).toBe(2)
})

test('a member who may not import sees no module at all', async ({ page, context }) => {
  // `imports.manage` is administrative. Hidden rather than locked, because
  // there is nothing to upsell: a customer who cannot get their data in has not
  // bought a product.
  await signInAs(context, { roles: ['member'], subject: 'e2e-plain-member' })

  await page.goto('/dashboard')
  await expect(page.getByRole('link', { name: /data import/i })).toHaveCount(0)

  await page.goto('/dashboard/imports')
  await expect(page.getByTestId('imports-panel')).toHaveCount(0)
})

test('a target with no writer offers no way to write', async ({ page, context }) => {
  // Absent rather than disabled, all the way down. A disabled control promises
  // a thing the product cannot do.
  await signInAs(context, { roles: ['organization_admin'], subject: 'e2e-subject' })
  await page.goto('/dashboard/imports')

  await expect(page.getByTestId('imports-confirm')).toHaveCount(0)
})

test('a past run opens, and its report holds every problem once', async ({
  page,
  context,
}) => {
  /*
   * IMP2-29 and IMP2-05 together.
   *
   * Before IMP2-29 the panel held its run in state that started `null` and was
   * never restored from the history, and the history was four cells with no
   * control — so a customer who reloaded could not reach the report for their
   * own run. The route answered; the page had no way in.
   */
  await signInAs(context, { roles: ['organization_admin'], subject: 'e2e-subject' })
  await page.goto('/dashboard/imports')

  const row = page.locator(`[data-run-id="${RUN_ID}"]`)
  await expect(row, 'the fixture run is not in the history').toHaveCount(1)
  await row.getByTestId('imports-open').click()

  const downloadButton = page.getByRole('button', { name: 'Download every problem' })
  await expect(downloadButton).toBeVisible()

  const download = page.waitForEvent('download')
  await downloadButton.click()
  const file = await download

  const stream = await file.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(Buffer.from(chunk))
  const text = Buffer.concat(chunks).toString('utf8').replace(/^﻿/, '')
  const body = parseCsv(text)
    .slice(1)
    .filter((r) => r.some((c) => c.length))

  // Every problem, once, in file order. Paging as shipped returned the first
  // page only, because the browser sent the file's line number to a route that
  // pages on the table's own key.
  expect(body.length).toBe(620)
  const numbers = body.map((r) => Number(r[0]))
  expect(new Set(numbers).size).toBe(620)
  expect([...numbers]).toEqual([...numbers].sort((a, b) => a - b))

  // A comma and doubled quotes survive as one cell rather than three rows.
  expect(body.find((r) => r[4].includes('with"quotes"'))?.[4]).toContain(',with"quotes"')

  // And nothing a spreadsheet would execute. These values came out of a file
  // somebody uploaded, and a cell that failed its check is the one most likely
  // to be hostile.
  const dangerous = body.map((r) => r[4]).filter((v) => /^[=+\-@\t\r]/.test(v))
  expect(
    dangerous,
    `these cells would be evaluated by a spreadsheet: ${dangerous.join(' | ')}`,
  ).toEqual([])
  expect(body.map((r) => r[4]).filter((v) => v.startsWith("'")).length).toBe(4)
})

/** A quoted field may hold a newline, so rows cannot be found by splitting. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let cell = ''
  let current: string[] = []
  let inQuotes = false
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"'
        i += 1
      } else if (ch === '"') inQuotes = false
      else cell += ch
    } else if (ch === '"') inQuotes = true
    else if (ch === ',') {
      current.push(cell)
      cell = ''
    } else if (ch === '\n') {
      current.push(cell)
      rows.push(current)
      current = []
      cell = ''
    } else if (ch !== '\r') cell += ch
  }
  if (cell.length || current.length) {
    current.push(cell)
    rows.push(current)
  }
  return rows
}
