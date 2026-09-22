import { expect, test } from '@playwright/test'
import { signInAs } from '../support/session'

/**
 * F28 manual cases 36 and 37, in a browser.
 *
 * The file a customer downloads when an import finds problems, fetched through
 * the product's own server action, its own API and a real database, and read
 * back as the bytes a spreadsheet would open.
 *
 * Two fixes meet here and neither is decidable by reading the code:
 *
 * *IMP2-05* — the route pages the report on the table's own key and the
 * browser used to send the file's row number. The seeded run has 620 problems
 * whose row numbers start at 10,000, which is what an ordinary file with its
 * bad rows late in it looks like, and what puts them on a different scale from
 * the identity column. Paging as shipped stopped after the first page.
 *
 * *IMP2-08* — a cell a spreadsheet would execute. Four of the seeded values
 * begin `=`, `+`, `@` and `-`, and the file must neutralise each.
 */

const RUN_ID = '22222222-2222-4222-8222-222222222222'

test('the downloaded report holds every problem, once, and executes nothing', async ({
  page,
  context,
}) => {
  await signInAs(context, { roles: ['organization_admin'], subject: 'e2e-owner' })
  await page.goto('/dashboard/imports')

  // The seeded run is in the history, and opening it is IMP2-29's fix. Before
  // it, there was no way to reach a run the page was not already working on.
  const row = page.locator(`[data-run-id="${RUN_ID}"]`)
  await expect(row).toHaveCount(1)
  await row.getByTestId('imports-open').click()

  // The result card is now showing that run, and the report control with it.
  await expect(page.getByTestId('imports-panel')).toBeVisible()
  const downloadButton = page.getByRole('button', { name: 'Download every problem' })
  await expect(downloadButton).toBeVisible()

  const download = page.waitForEvent('download')
  await downloadButton.click()
  const file = await download

  const stream = await file.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(Buffer.from(chunk))
  const text = Buffer.concat(chunks).toString('utf8').replace(/^﻿/, '')

  // A quoted field may hold a newline, so rows are counted by parsing rather
  // than by splitting on newlines -- which is the same mistake the file is
  // quoted to survive.
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
      } else if (ch === '"') {
        inQuotes = false
      } else {
        cell += ch
      }
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      current.push(cell)
      cell = ''
    } else if (ch === '\r') {
      // skip
    } else if (ch === '\n') {
      current.push(cell)
      rows.push(current)
      current = []
      cell = ''
    } else {
      cell += ch
    }
  }
  if (cell.length || current.length) {
    current.push(cell)
    rows.push(current)
  }

  const header = rows[0]
  const body = rows.slice(1).filter((r) => r.some((c) => c.length))

  // Case 36: every problem, exactly once, in file order.
  expect(body.length).toBe(620)
  const rowNumbers = body.map((r) => Number(r[0]))
  expect(new Set(rowNumbers).size).toBe(620)
  expect(rowNumbers[0]).toBe(10000)
  expect(rowNumbers[rowNumbers.length - 1]).toBe(10619)
  expect([...rowNumbers]).toEqual([...rowNumbers].sort((a, b) => a - b))

  // Case 37: a comma, a quote and a newline survive as one cell.
  expect(header.length).toBe(5)
  const withPunctuation = body.find((r) => r[4].includes('with"quotes"'))
  expect(withPunctuation, 'the cell holding a comma and quotes is missing').toBeDefined()
  expect(withPunctuation?.[4]).toContain(',with"quotes"')

  // Case 37 / IMP2-08: nothing a spreadsheet would evaluate.
  const values = body.map((r) => r[4])
  const dangerous = values.filter((v) => /^[=+\-@\t\r]/.test(v))
  expect(
    dangerous,
    `these cells would be evaluated by a spreadsheet: ${dangerous.join(' | ')}`,
  ).toEqual([])

  // And the four that were seeded are present, neutralised rather than dropped.
  const guarded = values.filter((v) => v.startsWith("'"))
  expect(guarded.length).toBe(4)
  expect(guarded.some((v) => v.startsWith("'=HYPERLINK("))).toBe(true)
  expect(guarded.some((v) => v === "'+1+1")).toBe(true)
  expect(guarded.some((v) => v === "'@SUM(1+1)")).toBe(true)
  expect(guarded.some((v) => v === "'-2+3")).toBe(true)
})
