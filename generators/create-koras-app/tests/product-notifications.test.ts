import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * In-app notifications, checked from the template text.
 *
 * CAT-01 Phase 1. Before 2026-09-19 a generated product had no bell, no feed,
 * no read state and no table — and a `notifications` capability declared
 * `true` in both profile manifests that gated nothing at all: no template map,
 * no defaults entry, and a `packages/notifications` two lines long. So
 * `--without notifications` removed nothing while appearing to succeed, and
 * the flag a generated project recorded in `.koras/project.yaml` claimed a
 * feature the project did not have.
 *
 * The properties worth a structural test are the ones that fail quietly.
 *
 * **The capability now gates a real set of files**, and the migration is
 * inside it. By the rule at `profiles/product/manifest.yaml` that is allowed
 * only because no foundation code and no foundation migration reaches the
 * table — every producer is inside a capability. `audit_events` failed that
 * test until 2026-09-16 and a product recorded nothing, invisibly.
 *
 * **A capability that produces notifications requires the one that stores
 * them.** `--with ai --without notifications` would generate an approval
 * notice whose import does not resolve. `requires` refuses it instead.
 *
 * **Every string is in all three catalogues.** A key present in English and
 * absent in German renders the key itself to a German customer.
 *
 * **The two settings nothing honours are unsurfaced.** Three were drawn on the
 * preferences page and read by nothing; one is honoured now and the other two
 * must not be offered until they are.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

type Manifest = {
  capabilities: Record<string, boolean>
  requires?: Record<string, string[]>
  template_map: { capabilities: Record<string, string | string[]> }
}

function manifest(): Manifest {
  return yaml.load(readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8')) as Manifest
}

function gatedPaths(capability: string): string[] {
  const entry = manifest().template_map.capabilities[capability]
  if (entry === undefined) return []
  return typeof entry === 'string' ? [entry] : entry
}

describe('in-app notifications', () => {
  it('gates a real set of files rather than nothing at all', () => {
    const paths = gatedPaths('notifications')
    expect(paths.length).toBeGreaterThan(0)

    // The pieces a product loses without it: the store, the routes, the table,
    // its isolation suite, the page and the browser test.
    for (const expected of [
      'services/api/koras_api/core/notifications.py',
      'services/api/koras_api/routers/notifications.py',
      'supabase/migrations/00032_notifications.sql',
      'supabase/tests/290_notifications_isolation.sql',
      'apps/web/src/app/dashboard/notifications',
      'e2e/notifications.spec.ts',
    ]) {
      expect(paths).toContain(expected)
    }
  })

  it('gates nothing that is not there', () => {
    // A path in the map that the template does not have is a capability that
    // silently excludes nothing, which is how this one spent its whole life.
    for (const path of gatedPaths('notifications')) {
      const direct = has(path)
      const templated = has(`${path}.hbs`)
      expect(direct || templated, `${path} is gated but not in the template`).toBe(true)
    }
  })

  it('is on by default and can be turned off', () => {
    const defaults = yaml.load(readFileSync(join(PROFILE, 'defaults.yaml'), 'utf8')) as {
      capabilities: Record<string, boolean>
    }

    expect(manifest().capabilities.notifications).toBe(true)
    // The entry that was missing: without it the flag resolved to true and
    // `--without notifications` had nothing to switch off.
    expect(defaults.capabilities.notifications).toBe(true)
  })

  it('refuses a producer without somewhere to produce into', () => {
    // `--with ai --without notifications` would generate `core/notify.py`
    // importing `core/notifications.py`, which would not be there.
    expect(manifest().requires?.ai).toContain('notifications')
  })

  it('keeps the shared UI, the settings and the strings out of the gate', () => {
    // Generated always and harmless without the capability, exactly as the
    // assistant's and the reporting components are.
    for (const path of gatedPaths('notifications')) {
      expect(path).not.toContain('packages/ui')
      expect(path).not.toContain('settings_catalogue')
      expect(path).not.toContain('packages/i18n')
    }
  })

  it('registers one module, with neither a permission nor an entitlement', () => {
    const branding = read('packages/branding/src/index.ts.hbs')
    expect(branding).toContain("id: 'notifications'")
    expect(branding).toContain("href: '/dashboard/notifications'")
    expect(branding).toContain("requiredCapabilities: ['notifications']")

    // The href resolves to a real route.
    expect(has('apps/web/src/app/dashboard/notifications/page.tsx.hbs')).toBe(true)

    // The bell glyph existed in the icon union and was drawn by nothing until
    // this module used it.
    expect(read('packages/ui/src/primitives/icon.tsx.hbs')).toContain('bell:')
  })

  it('draws the bell from the layout rather than polling for it', () => {
    const layout = read('apps/web/src/app/dashboard/layout.tsx.hbs')
    expect(layout).toContain('NotificationBell')
    expect(layout).toContain('loadNotifications')
    // Honouring the preference is the whole reason the layout reads it.
    expect(layout).toContain("settingValue(settings?.settings['notifications.inAppEnabled']")

    // The header slot is no longer gated on the assistant alone: a product
    // with notifications and without `ai` still gets one.
    expect(layout).toContain('headerActions={headerActions}')
  })

  it('offers no control it does not honour', () => {
    const catalogue = read('services/api/koras_api/settings_catalogue/standard.py')
    const section = catalogue.slice(
      catalogue.indexOf('"notifications.inAppEnabled"'),
      catalogue.indexOf('"files.maxUploadSizeMb"'),
    )
    // The two with no consumer are unsurfaced; the one the layout reads is not.
    expect(section.match(/surfaced=False/g) ?? []).toHaveLength(2)
    expect(section.indexOf('surfaced=False')).toBeGreaterThan(
      section.indexOf('"notifications.emailEnabled"'),
    )
  })

  it('carries every string in all three catalogues', () => {
    const keys = [
      'notifications.title',
      'notifications.unread',
      'notifications.empty',
      'notifications.emptyHint',
      'notifications.markAllRead',
      'notifications.markRead',
      'notifications.dismiss',
      'notifications.close',
      'notifications.viewAll',
      'notifications.pageTitle',
      'notifications.pageDescription',
      'notifications.hiddenTitle',
      'notifications.hiddenBody',
    ]
    for (const locale of ['en', 'de', 'es']) {
      const catalogue = read(`packages/i18n/src/messages/${locale}.ts`)
      for (const key of keys) {
        expect(catalogue, `${locale} is missing ${key}`).toContain(`'${key}'`)
      }
    }
  })

  it('writes no notification from a route', () => {
    // A create route would let any signed-in person put a message in a
    // colleague's feed under the product's own branding.
    const router = read('services/api/koras_api/routers/notifications.py')
    expect(router).not.toContain('async def create')
    expect(router.match(/@router\.post/g) ?? []).toHaveLength(2)
    expect(router).toContain('/notifications/read-all')
    expect(router).toContain('/notifications/unread-count')
  })

  it('sweeps the feed on a schedule nothing else uses', () => {
    const worker = read('services/worker/koras_worker/worker.py.hbs')
    expect(worker).toContain('purge_notifications')
    expect(worker).toContain('hour=3, minute=19')
    // The starter's own sweeps run between 03:17 and 04:39 and must not
    // collide; 03:19 was free.
    expect(worker.match(/minute=19/g) ?? []).toHaveLength(1)
  })

  it('extracts the drawer rather than writing a third focus trap', () => {
    // The assistant's drawer carried a note saying a second copy of the trap
    // was cheaper than a library for two panels. This is the third.
    expect(has('packages/ui/src/primitives/drawer.tsx')).toBe(true)
    const ai = read('packages/ui/src/ai/ai-drawer.tsx')
    expect(ai).toContain("from '../primitives/drawer'")
    expect(ai).not.toContain('addEventListener')
    // The assistant keeps its two differences: where focus lands, and what the
    // browser tests look for.
    expect(ai).toContain('initialFocusSelector="textarea"')
    expect(ai).toContain('testId="assistant-drawer"')
  })
})
