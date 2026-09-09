import { expect, test } from '@playwright/test'
import { signInAs } from './support/session'

/**
 * The Files module, in a browser without a bucket.
 *
 * The suite runs against `next start` with a session secret and no API, so
 * the bucket, the API and the platform are all absent. That is the state
 * worth proving here: a page whose backing services are missing must say so
 * and offer a retry, never a blank table or a spinner that stays. The upload
 * itself is exercised by the API's own tests against MinIO and by the smoke
 * check against a deployed environment, where there is something to upload to.
 */

test('the module is in the sidebar and the page names its state', async ({ page, context }) => {
  await signInAs(context)
  await page.goto('/dashboard/files')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Files')

  // No API: the panel reports it as an error with a way to try again, and the
  // upload control is still there because the caller may upload.
  const panel = page.getByTestId('files')
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Try again' })).toBeVisible()
  await expect(page.getByTestId('files-upload')).toBeVisible()
})

test('a member may upload and may not delete; the controls say so', async ({ page, context }) => {
  await signInAs(context, { roles: ['member'] })
  await page.goto('/dashboard/files')
  await expect(page.getByTestId('files-upload')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(0)
})

test('the page is translated with the rest of the shell', async ({ page, context }) => {
  await signInAs(context)
  await page.goto('/dashboard/settings')
  await page.getByLabel(/Show .* in/).selectOption('de')
  await page.getByRole('button', { name: 'Change language' }).click()
  await page.goto('/dashboard/files')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Dateien')
  await expect(page.getByTestId('files-upload')).toHaveText('Datei hochladen')
})
