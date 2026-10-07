import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { signInAs } from '../support/session'

/**
 * The Files page shows what the server released and nothing else (ADR 0013, `secure_files`).
 *
 * Rows are written straight into `public.files` as the migration superuser,
 * one per stored verdict, because no scanner is running in this stack and the
 * page's whole job is to render a verdict it did not decide. A releasable one is
 * what the scanner leaves: a clean verdict on this tenant's own final key, stamped
 * with the identity it was bound to. Everything the
 * browser sees comes through the real API, the real release rule and RLS.
 *
 * Not constructible here, and proved by the component suite instead: a `NULL`
 * or unrecognised `scan_status` (the column is `NOT NULL` with a `CHECK`).
 *
 * The Download that actually releases bytes needs a bucket this stack does not
 * have; the API's own tests cover signing. What is proved here is the other half:
 * no working Download for what is not released, and a safe ending when the page
 * is stale.
 */

const ADMIN_URL = process.env.E2E_ADMIN_DATABASE_URL ?? process.env.MIGRATE_DATABASE_URL ?? ''
const TENANT = '00000000-0000-4e2e-8000-000000000001'
const OTHER_TENANT = '00000000-0000-4e2e-8000-000000000002'
const GENERATION = '00000000-0000-4e2e-8000-0000000000ff'
const PREFIX = 'release-state-'

// The round-trip project exists only when `E2E_DATABASE_URL` does, and this spec also needs a
// superuser connection to write the verdicts a scanner would.
test.skip(
  !ADMIN_URL,
  'needs a superuser connection (E2E_ADMIN_DATABASE_URL) to write the stored verdicts',
)
test.describe.configure({ mode: 'serial' })
// This spec deletes rows by name as the superuser. Refuse anything but a local database.
const HOST = ADMIN_URL ? new URL(ADMIN_URL).hostname : ''
test.skip(
  Boolean(ADMIN_URL) && !['localhost', '127.0.0.1', '::1', '[::1]'].includes(HOST),
  'refuses to seed and delete as a superuser on a database that is not local',
)

function sql(statement: string): string {
  return execFileSync('psql', ['-v', 'ON_ERROR_STOP=1', '-qtA', ADMIN_URL, '-c', statement], {
    encoding: 'utf8',
  }).trim()
}

function seed(tenant: string, slug: string, scan: string, status = 'ready'): string {
  const id = sql('select gen_random_uuid()')
  // A clean verdict is stamped by the scanner; nothing else is, and a verdict that is not clean
  // has no identity to carry.
  const etag = scan === 'clean' ? "'etag-1'" : 'null'
  sql(
    `insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type,
       category, status, scan_status, scan_object_etag, uploaded_by, ready_at)
     values ('${id}', '${tenant}',
       'tenants/${tenant}/documents/${id}/final/${GENERATION}/${PREFIX}${slug}.pdf',
       '${PREFIX}${slug}.pdf', 100, 'application/pdf', 'documents', '${status}', '${scan}', ${etag},
       'e2e-subject', now())`,
  )
  return id
}

function cleanUp() {
  sql(`delete from public.files where name like '${PREFIX}%'`)
}

test.beforeAll(() => {
  cleanUp()
  sql(
    `insert into public.tenants (id, slug, name, zitadel_org_id, status, owner_email)
     values ('${OTHER_TENANT}', 'e2e-other', 'Another organisation', 'e2e-other-organization',
       'active', 'other@example.com')
     on conflict (zitadel_org_id) do nothing`,
  )
  seed(TENANT, 'clean', 'clean')
  seed(TENANT, 'pending', 'pending')
  seed(TENANT, 'charlie', 'skipped')
  // The two ways an infected file can reach the API: quarantined (the scanner's own
  // write, never listed) and the odd row that still says ready.
  seed(TENANT, 'delta', 'infected')
  seed(TENANT, 'echo', 'infected', 'quarantined')
  seed(OTHER_TENANT, 'other-tenant', 'clean')
})
test.afterAll(cleanUp)

const row = (page: Page, slug: string) =>
  page.getByTestId('file-row').filter({ hasText: `${PREFIX}${slug}.pdf` })
const download = (page: Page, slug: string) =>
  row(page, slug).getByRole('button', { name: 'Download' })

/**
 * Press Download and wait for the page's answer, a notice.
 *
 * The server-rendered row is enabled before the client has hydrated, and a click that lands in
 * that gap does nothing, so the page is left to go quiet first. The answer is then slow by
 * construction: a server action runs the API's whole request, and the API in this stack has no
 * rate-limit store to reach, so each call spends its connection attempt before it is allowed.
 */
async function pressAndWaitForNotice(page: Page, slug: string, sentence: string | RegExp) {
  await page.waitForLoadState('networkidle')
  await download(page, slug).click()
  await expect(page.getByTestId('files-notice')).toContainText(sentence, { timeout: 45_000 })
}

test('each stored verdict is shown as the state the server released it as', async ({ page, context }) => {
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(page.getByTestId('files')).toBeVisible()

  await expect(row(page, 'clean')).toHaveAttribute('data-state', 'available')
  await expect(download(page, 'clean')).toBeEnabled()

  for (const slug of ['pending', 'charlie', 'delta']) {
    await expect(download(page, slug), slug).toBeDisabled()
  }
  await expect(row(page, 'pending')).toHaveAttribute('data-state', 'scanning')
  await expect(row(page, 'pending')).toContainText('Being checked')
  await expect(row(page, 'charlie')).toHaveAttribute('data-state', 'unavailable')
  await expect(row(page, 'delta')).toHaveAttribute('data-state', 'unavailable')

  // A quarantined file is not listed, and another tenant's file is not either.
  await expect(row(page, 'echo')).toHaveCount(0)
  await expect(row(page, 'other-tenant')).toHaveCount(0)

  // Nothing a scanner knows, and the old sentence is gone.
  const body = page.getByTestId('files')
  await expect(body).not.toContainText(/infect|malware|virus|quarantin|signature|skipped|Indexing/i)
  await expect(page.getByTestId('files-scanning')).toBeVisible()
  // Being checked is not a fault.
  await expect(page.getByTestId('files').getByRole('alert')).toHaveCount(0)
})

test('the assistant column says nothing about indexing for a file awaiting its check', async ({
  page,
  context,
}) => {
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(
    row(page, 'pending').getByTestId('file-searchable'),
  ).toHaveText('After the file is available')
  await expect(row(page, 'clean').getByTestId('file-searchable')).toHaveText('Not indexed yet')
})

test('a disabled Download cannot be reached by keyboard or clicked', async ({ page, context }) => {
  await signInAs(context)
  await page.goto('/dashboard/files')
  const pending = download(page, 'pending')
  await expect(pending).toBeDisabled()
  await pending.focus().catch(() => undefined)
  await expect(pending).not.toBeFocused()
  await expect(pending).toHaveAttribute('aria-describedby', /file-status-/)
  await expect(page.getByTestId('files-notice')).toHaveCount(0)
})

test('stale page: the server refuses a file that stopped being released, and the page ends safe', async ({
  page,
  context,
}) => {
  test.setTimeout(90_000)
  const id = seed(TENANT, 'foxtrot', 'clean')
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(download(page, 'foxtrot')).toBeEnabled()

  // The verdict moves on behind the page's back.
  sql(
    `update public.files set scan_status = 'pending', scan_object_etag = null where id = '${id}'`,
  )
  let navigated = false
  page.on('framenavigated', () => {
    navigated = true
  })
  await pressAndWaitForNotice(page, 'foxtrot', 'This file is not available.')

  await expect(row(page, 'foxtrot')).toHaveAttribute('data-state', 'scanning')
  await expect(download(page, 'foxtrot')).toBeDisabled()
  await expect(page.getByTestId('files').getByRole('alert')).toHaveCount(0)
  expect(navigated).toBe(false)
  expect(page.url()).toContain('/dashboard/files')
})

test('stale page: a file quarantined behind the page gets only a generic sentence', async ({
  page,
  context,
}) => {
  test.setTimeout(90_000)
  const id = seed(TENANT, 'golf', 'clean')
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(download(page, 'golf')).toBeEnabled()

  sql(
    `update public.files set scan_status = 'infected', status = 'quarantined',
       scan_object_etag = null where id = '${id}'`,
  )
  await pressAndWaitForNotice(page, 'golf', 'This file is not available.')

  const notice = page.getByTestId('files-notice')
  await expect(notice).toHaveText('This file is not available.')
  await expect(notice).not.toContainText(/scan|secur|infect|withheld/i)
  await expect(row(page, 'golf')).toHaveCount(0)
})

test('a file that is checked while the page is open becomes available without a reload', async ({
  page,
  context,
}) => {
  test.setTimeout(60_000)
  const id = seed(TENANT, 'becomes-clean', 'pending')
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(download(page, 'becomes-clean')).toBeDisabled()

  sql(
    `update public.files set scan_status = 'clean', scan_object_etag = 'etag-1' where id = '${id}'`,
  )
  // The first bounded refresh is ten seconds out.
  await expect(row(page, 'becomes-clean')).toHaveAttribute('data-state', 'available', {
    timeout: 30_000,
  })
  await expect(download(page, 'becomes-clean')).toBeEnabled()
})

test('it is usable at a phone width, with the status still in text', async ({ page, context }) => {
  seed(TENANT, 'hotel', 'pending')
  await signInAs(context)
  await page.setViewportSize({ width: 375, height: 800 })
  await page.goto('/dashboard/files')
  await expect(row(page, 'hotel')).toContainText('Being checked')
  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  )
  const wide = await page.evaluate(() =>
    [...document.querySelectorAll('body *')]
      .filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
      .filter((el) => !el.parentElement?.closest('.overflow-x-auto'))
      .slice(0, 8)
      .map((el) => `${el.tagName}.${String(el.className).slice(0, 60)}`),
  )
  expect(overflows, `overflowing: ${wide.join(' | ')}`).toBe(false)
})
