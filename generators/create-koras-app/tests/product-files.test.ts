import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { templatePath } from './template-path'

/**
 * The Files module, checked from the template text.
 *
 * The module crosses four boundaries -- a table with policies, a Python
 * package that signs URLs, an API that records rows, and a page that never
 * sees a byte -- and each boundary has a name the other side must agree on.
 * These are the agreements, asserted here because no single test suite sees
 * both sides of any of them: the RLS suite proves the policies say what they
 * say, the package tests prove resolution, and this proves the names match.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8')
}

describe('the table', () => {
  const migration = read('supabase', 'migrations', '00005_files.sql')

  it('is scoped, forced and policed like every tenant table', () => {
    expect(migration).toContain('tenant_id     uuid not null references public.tenants(id)')
    expect(migration).toContain('alter table public.files enable row level security;')
    expect(migration).toContain('alter table public.files force row level security;')
    for (const verb of ['select', 'insert', 'update', 'delete']) {
      expect(migration, `no ${verb} policy`).toMatch(new RegExp(`on public\\.files for ${verb}`))
    }
    // Writes carry `with check`; a `using`-only policy admits a row it then hides.
    expect(migration).toMatch(/for insert\s+with check \(tenant_id = public\.current_tenant_id\(\)\)/)
  })

  it('holds no bytes and no credential', () => {
    expect(migration).not.toMatch(/bytea/)
    expect(migration).not.toMatch(/secret|access_key/i)
  })

  it('is exercised by the isolation suite', () => {
    const suite = read('supabase', 'tests', '050_files_isolation.sql')
    expect(suite).toContain('set local role koras_rls_test;')
    expect(suite).toContain("raise exception 'files: another tenant''s file was visible'")
    expect(suite).toContain('an insert into another tenant was admitted')
  })
})

describe('the names the two sides share', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')
  const permissions = read('packages', 'permissions', 'src', 'index.ts')
  const storage = read('services', 'api', 'koras_api', 'core', 'storage.py')
  const router = read('services', 'api', 'koras_api', 'routers', 'files.py')

  it('gates the module on the same entitlement the API enforces', () => {
    expect(storage).toContain('STORAGE_ENTITLEMENT = "storage.files"')
    expect(branding).toMatch(/id: 'files',[\s\S]*?requiredEntitlements: \['storage\.files'\]/)
    expect(router).toContain('status.HTTP_402_PAYMENT_REQUIRED')
  })

  it('names the three permissions in the catalogue and maps them the way the API does', () => {
    for (const permission of ['files.read', 'files.upload', 'files.manage']) {
      expect(permissions).toContain(`'${permission}'`)
    }
    // Members read and upload; only owners and admins delete. The API mirrors
    // the second half by role, since it cannot import the catalogue.
    expect(permissions).toMatch(/member: \['product\.access', 'files\.read', 'files\.upload'\]/)
    expect(router).toContain('_MANAGERS = (OrganizationRole.OWNER, OrganizationRole.ADMIN)')
    expect(branding).toMatch(/id: 'files',[\s\S]*?requiredPermissions: \['files\.read'\]/)
  })

  it('serves the page the module points at', () => {
    expect(existsSync(join(PRODUCT, 'apps', 'web', 'src', 'app', 'dashboard', 'files', 'page.tsx.hbs'))).toBe(true)
  })
})

describe('no byte passes through the product', () => {
  const panel = read('apps', 'web', 'src', 'app', 'dashboard', 'files', 'FilesPanel.tsx.hbs')
  const actions = read('apps', 'web', 'src', 'app', 'dashboard', 'files', 'actions.ts.hbs')
  const router = read('services', 'api', 'koras_api', 'routers', 'files.py')

  it('uploads and downloads on signed URLs the API mints', () => {
    expect(panel).toContain("xhr.open('PUT', url)")
    expect(panel).toContain('ticket.value.upload_url')
    expect(router).toContain('presign_upload(')
    expect(router).toContain('presign_download(')
    // The API confirms the object before the row is listed.
    expect(router).toContain('storage.store.head(row.storage_key)')
  })

  it('lets the browser reach the bucket the API signs for', () => {
    // The upload is a PUT from the browser to the storage origin. A policy
    // that names only the API refuses it, and the page reports the bucket as
    // unreachable -- which is what the first live upload did.
    const middleware = read('apps', 'web', 'src', 'middleware.ts.hbs')
    expect(middleware).toContain('function storageOrigin()')
    expect(middleware).toContain('process.env.STORAGE_ENDPOINT')
    expect(middleware).toContain("`${process.env.NEXT_PUBLIC_API_URL ?? ''} ${storageOrigin()}`.trim()")
  })

  it('keeps the API address and the token on the server', () => {
    expect(panel).not.toContain('NEXT_PUBLIC_API_URL')
    expect(panel).not.toContain('providerToken')
    expect(actions).toContain("'use server'")
    expect(actions).toContain('providerToken()')
  })
})

describe('the settings', () => {
  const manifest = read('local', 'config', 'secrets.manifest.hbs')
  const settings = read('services', 'api', 'koras_api', 'core', 'settings.py.hbs')

  it('declares every storage setting the API reads', () => {
    for (const name of [
      'STORAGE_ENDPOINT',
      'STORAGE_BUCKET',
      'STORAGE_REGION',
      'STORAGE_ACCESS_KEY',
      'STORAGE_SECRET_KEY',
      'STORAGE_R2_ACCESS_KEY',
      'STORAGE_R2_SECRET_KEY',
      'STORAGE_S3_ACCESS_KEY',
      'STORAGE_S3_SECRET_KEY',
    ]) {
      expect(manifest, `${name} is read but not declared`).toMatch(new RegExp(`^${name} `, 'm'))
      expect(settings).toContain(name.toLowerCase())
    }
  })

  it('points a deployed product at the S3 gateway, not the REST root', () => {
    const terraform = read('infrastructure', 'terraform', 'main.tf.hbs')
    expect(terraform).toContain('"https://${ref}.storage.supabase.co/storage/v1/s3"')
  })
})
