import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * The reporting framework, checked from the template text.
 *
 * Like the AI foundation, it crosses boundaries no single suite sees both
 * sides of: an entitlement named in the API and in the navigation registry,
 * three permissions in two languages, a capability with a path list, a
 * module whose route has to exist, a migration whose policies have to be
 * forced, and a package that must run no query. The framework's behaviour
 * is tested where it lives; this proves the names match.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const STARTER = join(PRODUCT, '..', '..', '..')
const SHARED = join(STARTER, 'profiles', '_shared', 'template')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

// ── the audit table ───────────────────────────────────────────────────────────

describe('the audit table', () => {
  const migration = read('supabase', 'migrations', '00013_audit_events.sql')

  it('is scoped, forced and policed like every tenant table', () => {
    expect(migration).toMatch(
      /create table public\.audit_events \([\s\S]*?tenant_id\s+uuid not null references public\.tenants\(id\)/,
    )
    expect(migration).toContain('alter table public.audit_events enable row level security;')
    expect(migration).toContain('alter table public.audit_events force row level security;')
    expect(migration).toMatch(
      /on public\.audit_events for insert\s+with check \(tenant_id = public\.current_tenant_id\(\)\)/,
    )
  })

  it('lets nobody rewrite an audit row', () => {
    expect(migration).not.toMatch(/on public\.audit_events for update/)
    // The one delete is the retention sweep's, on the provisioning context.
    expect(migration).toMatch(/for delete\s+using \(public\.is_provisioning\(\)\)/)
  })

  it('is exercised by the isolation suite', () => {
    const suite = read('supabase', 'tests', '110_audit_isolation.sql')
    expect(suite).toContain('set local role koras_rls_test;')
    expect(suite).toContain("raise exception 'audit: a row was written into another tenant'")
    expect(suite).toContain("raise exception 'audit: a row was rewritten'")
  })
})

// ── the names the sides share ─────────────────────────────────────────────────

describe('the names the sides share', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')
  const permissions = read('packages', 'permissions', 'src', 'index.ts')
  const pyPermissions = read('python-packages', 'koras-auth', 'src', 'koras_auth', 'permissions.py')
  const core = read('services', 'api', 'koras_api', 'core', 'reporting.py.hbs')
  const standard = read('services', 'api', 'koras_api', 'reporting', 'standard.py.hbs')
  const router = read('services', 'api', 'koras_api', 'routers', 'reporting.py')

  it('gates the module on the same entitlement the API enforces', () => {
    expect(core).toContain('REPORTING_ENTITLEMENT = "reporting.basic"')
    expect(standard).toContain('BASIC = "reporting.basic"')
    expect(branding).toMatch(/id: 'analytics'[\s\S]*?requiredEntitlements: \['reporting\.basic'\]/)
  })

  it('names the same three permissions in both catalogues and the registry', () => {
    for (const permission of ['reports.read', 'reports.sensitive', 'reports.export']) {
      expect(permissions).toContain(`'${permission}'`)
      expect(pyPermissions).toContain(`"${permission}"`)
    }
    expect(branding).toMatch(/id: 'analytics'[\s\S]*?requiredPermissions: \['reports\.read'\]/)
    expect(core).toContain('READ_PERMISSION = "reports.read"')
    expect(core).toContain('EXPORT_PERMISSION = "reports.export"')
    expect(router).toContain('EXPORT_PERMISSION not in reporting.context.permissions')
  })

  it('gives every recognised role the read permission and no member the export', () => {
    expect(permissions).toMatch(/member: \[[^\]]*'reports\.read'[^\]]*\]/)
    expect(permissions).not.toMatch(/member: \[[^\]]*'reports\.export'[^\]]*\]/)
    expect(pyPermissions).toMatch(/_EVERYONE[\s\S]*?"reports\.read"/)
  })

  it('puts the module on a route that exists and behind the capability', () => {
    expect(branding).toMatch(/id: 'analytics'[\s\S]*?href: '\/dashboard\/analytics'/)
    expect(branding).toMatch(/id: 'analytics'[\s\S]*?requiredCapabilities: \['reporting'\]/)
    expect(has('apps', 'web', 'src', 'app', 'dashboard', 'analytics', 'page.tsx.hbs')).toBe(true)
    expect(has('apps', 'web', 'src', 'app', 'dashboard', 'analytics', '[report]', 'page.tsx.hbs')).toBe(
      true,
    )
    // The placeholder it replaced is gone; `insights` stays as the hide example.
    expect(has('apps', 'web', 'src', 'app', 'dashboard', 'reports')).toBe(false)
    expect(branding).not.toContain("id: 'reports'")
    expect(branding).toContain("id: 'insights'")
  })

  it('translates every analytics key in every catalogue', () => {
    const en = read('packages', 'i18n', 'src', 'messages', 'en.ts')
    const keys = [...en.matchAll(/'(analytics\.[a-zA-Z.]+)'/g)].map((m) => m[1] as string)
    expect(keys.length).toBeGreaterThan(20)
    for (const locale of ['de', 'es']) {
      const catalogue = read('packages', 'i18n', 'src', 'messages', `${locale}.ts`)
      for (const key of keys) expect(catalogue, `${locale} lacks ${key}`).toContain(`'${key}'`)
    }
  })
})

// ── the boundary ──────────────────────────────────────────────────────────────

describe('the boundary', () => {
  const router = read('services', 'api', 'koras_api', 'routers', 'reporting.py')
  const standard = read('services', 'api', 'koras_api', 'reporting', 'standard.py.hbs')

  it('decides visibility before a resolver runs and hides as 404', () => {
    expect(router).toContain('visibility is Visibility.HIDDEN')
    expect(router).toContain('status_code=status.HTTP_404_NOT_FOUND, detail="no such report"')
    expect(router).toContain('HTTP_402_PAYMENT_REQUIRED')
  })

  it('binds the tenant in every standard statement and interpolates only the bucket', () => {
    const statements = [...standard.matchAll(/^_[A-Z_]+ = \(\n([\s\S]*?)\n\)/gm)].map(
      (m) => m[1] as string,
    )
    expect(statements.length).toBeGreaterThan(8)
    for (const statement of statements) {
      expect(statement, statement).toContain(':tenant_id')
      // The only f-string-style hole is the bucket, chosen from three words.
      const holes = [...statement.matchAll(/\{([a-z_]+)\}/g)].map((m) => m[1])
      expect(holes.every((hole) => hole === 'bucket'), statement).toBe(true)
    }
    expect(standard).toContain('_BUCKETS = {"day": "day", "week": "week", "month": "month"}')
  })

  it('records exports and sensitive views to the audit table', () => {
    expect(router).toContain('"report.exported"')
    expect(router).toContain('"report.viewed"')
    expect(router).toContain('await reporting.flush()')
  })

  it('exposes no content from the assistant in the usage report', () => {
    const ai = standard.slice(standard.indexOf('_AI_TOTALS'), standard.indexOf('# ── the resolvers'))
    expect(ai).not.toMatch(/content|conversation_id|user_id/)
  })

  it('keeps the framework free of a database driver', () => {
    const pyproject = readFileSync(
      join(SHARED, 'python-packages', 'koras-reporting', 'pyproject.toml'),
      'utf8',
    )
    expect(pyproject).not.toMatch(/sqlalchemy|asyncpg|psycopg/)
    const filters = readFileSync(
      join(SHARED, 'python-packages', 'koras-reporting', 'src', 'koras_reporting', 'filters.py'),
      'utf8',
    )
    expect(filters).toContain('MAX_RANGE_DAYS = 366')
  })

  it('reaches the browser through a route handler that never prefetches', () => {
    const page = read('apps', 'web', 'src', 'app', 'dashboard', 'analytics', 'ReportPage.tsx.hbs')
    expect(page).toContain('/api/reports/')
    const menu = read('packages', 'ui', 'src', 'reporting', 'export-menu.tsx')
    expect(menu).toContain('ButtonLink')
    const handler = read('apps', 'web', 'src', 'app', 'api', 'reports', '[key]', 'export', 'route.ts.hbs')
    expect(handler).toContain("can(signedIn.access, 'reports.export')")
    const download = read(
      'apps', 'web', 'src', 'app', 'api', 'reports', 'exports', '[id]', 'download', 'route.ts.hbs',
    )
    expect(download).toContain("can(signedIn.access, 'reports.export')")
  })
})

// ── schedules, exports and delivery ───────────────────────────────────────────

describe('scheduled delivery and background exports', () => {
  const schedules = read('services', 'api', 'koras_api', 'routers', 'reporting_schedules.py')
  const router = read('services', 'api', 'koras_api', 'routers', 'reporting.py')
  const worker = read('services', 'worker', 'koras_worker', 'tasks', 'reporting.py')
  const migration = read('supabase', 'migrations', '00014_report_schedules.sql')

  it('gates a schedule on the export permission, the export plan and the scheduled plan', () => {
    expect(schedules).toContain('require_exporter(reporting)')
    expect(schedules).toContain('reporting.grant.can_schedule')
    expect(schedules).toContain('reporting.scheduled')
    const core = read('services', 'api', 'koras_api', 'core', 'reporting.py.hbs')
    expect(core).toContain('REPORTING_SCHEDULED_ENTITLEMENT = "reporting.scheduled"')
  })

  it('validates at creation everything the worker later trusts', () => {
    expect(schedules).toContain('the period is decided by the cadence, not by a filter')
    expect(schedules).toContain('resolve_filters(definition, body.filters)')
    expect(schedules).toContain('export_format(definition, body.format)')
    expect(schedules).toContain('MAX_RECIPIENTS = 10')
  })

  it('answers a large export with 202 and writes it after the response', () => {
    expect(router).toContain('rows > EXPORT_ROW_LIMIT or wanted_background')
    expect(router).toContain('HTTP_202_ACCEPTED')
    expect(router).toContain('background.add_task(')
    expect(router).toContain('write_export,')
    expect(router).toContain('tenants/{tenant_id}/exports/{export_id}/')
  })

  it('offers the three formats and names each by its media type', () => {
    const exp = readFileSync(
      join(SHARED, 'python-packages', 'koras-reporting', 'src', 'koras_reporting', 'export.py'),
      'utf8',
    )
    expect(exp).toContain('text/csv; charset=utf-8')
    expect(exp).toContain('spreadsheetml.sheet')
    expect(exp).toContain('application/pdf')
  })

  it('delivers as the tenant and records the run either way', () => {
    expect(worker).toContain("set_config('app.tenant_id', :tenant_id, true)")
    expect(worker).toContain('"report.delivered"')
    expect(worker).toContain('last_error = :error')
    expect(worker).toContain('UNRESOLVED_PLAN')
  })

  it('asks the synced plan the same three gates before delivering', () => {
    expect(worker).toContain('from public.tenant_plans where tenant_id = :tenant_id')
    expect(worker).toContain('class PlanLapsed(Exception)')
    expect(worker).toContain('for code in (SCHEDULED, EXPORT, definition.entitlement):')
    const platform = read('services', 'api', 'koras_api', 'routers', 'platform.py')
    expect(platform).toContain('@router.put("/tenants/{tenant_id}/plan"')
    const contract = JSON.parse(
      readFileSync(join(SHARED, 'contracts', 'product-platform.v1.json'), 'utf8'),
    ) as { routes: { method: string; path: string; capability?: string }[] }
    expect(contract.routes).toContainEqual(
      expect.objectContaining({ method: 'put', path: '/tenants/{tenant_id}/plan' }),
    )
    expect(contract.routes).toContainEqual(
      expect.objectContaining({ method: 'get', path: '/activity', capability: 'reporting' }),
    )
    const migration = read('supabase', 'migrations', '00015_tenant_plans.sql')
    expect(migration).toContain('alter table public.tenant_plans force row level security;')
    expect(migration).not.toMatch(/tenant_plans_(insert|update)_own_tenant/)
  })

  it('reads the catalogue by name and the worker declares no API dependency', () => {
    expect(worker).toContain('importlib.import_module("koras_api.reporting")')
    const pyproject = readFileSync(join(SHARED, 'services', 'worker', 'pyproject.toml.hbs'), 'utf8')
    expect(pyproject).not.toContain('koras-api')
    const dockerfile = readFileSync(join(SHARED, 'services', 'worker', 'Dockerfile.hbs'), 'utf8')
    expect(dockerfile).toContain('{{#if capability.reporting}}')
    expect(dockerfile).toContain('COPY services/api/koras_api/reporting/')
  })

  it('polices both tables and lets only the worker read every schedule', () => {
    for (const table of ['report_schedules', 'report_exports']) {
      expect(migration).toContain(`alter table public.${table} enable row level security;`)
      expect(migration).toContain(`alter table public.${table} force row level security;`)
    }
    expect(migration).toMatch(/report_schedules[\s\S]*?for select[\s\S]*?is_provisioning\(\)/)
    const exportsPart = migration.slice(migration.indexOf('create table public.report_exports'))
    expect(exportsPart).not.toContain('is_provisioning')
    const suite = read('supabase', 'tests', '130_report_schedules_isolation.sql')
    expect(suite).toContain('set local role koras_rls_test;')
  })
})

// ── the capability ────────────────────────────────────────────────────────────

describe('the capability', () => {
  const manifest = yaml.load(
    readFileSync(join(STARTER, 'profiles', 'product', 'manifest.yaml'), 'utf8'),
  ) as {
    capabilities: Record<string, boolean>
    template_map: { capabilities: Record<string, string | string[]> }
  }
  const defaults = yaml.load(
    readFileSync(join(STARTER, 'profiles', 'product', 'defaults.yaml'), 'utf8'),
  ) as { capabilities: Record<string, boolean> }

  it('is declared, on by default, and needs nothing beside it', () => {
    expect(manifest.capabilities.reporting).toBe(true)
    expect(defaults.capabilities.reporting).toBe(true)
  })

  it('gates paths that all exist in the template', () => {
    const paths = manifest.template_map.capabilities.reporting
    expect(Array.isArray(paths)).toBe(true)
    for (const path of paths as string[]) {
      const found = has(path) || has(`${path}.hbs`)
      expect(found, `${path} is gated but absent from the template`).toBe(true)
    }
  })

  it('ships the framework in the shared layer for both profiles', () => {
    expect(existsSync(join(SHARED, 'python-packages', 'koras-reporting', 'pyproject.toml'))).toBe(true)
    expect(read('pyproject.toml.hbs')).toContain('koras-reporting = { workspace = true }')
  })
})
