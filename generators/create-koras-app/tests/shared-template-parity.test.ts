import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Files the two profiles hold byte-identical copies of.
 *
 * The starter has no shared template layer, so every one of these exists twice.
 * That is the mechanism behind most of this repository's recurring defects: a
 * fix lands in one profile, the other keeps the old version, and nothing in a
 * review of either repository shows it. The Control Plane's session work, its
 * dependency declarations and its RLS ordering each reached one side and sat
 * there for weeks.
 *
 * Listing them explicitly is the point. A file leaving this set is a deliberate
 * divergence someone should have to justify in a diff, not something that
 * happens by forgetting.
 *
 * This is a guard, not the fix. The fix is a `profiles/_shared/` tree, which
 * `shared_assets` cannot carry as it stands because it copies verbatim and most
 * of these need rendering. Until then, this turns silent drift into a failing
 * build.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')

// Deliberately absent: infrastructure/terraform/terraform.tfvars.hbs. Its
// commented `zitadel_role_grants` example names the owner role of the profile
// it belongs to -- organization_owner for a product, platform_super_admin for
// the Control Plane -- and an example naming a role the project does not define
// is worse than none, because it is the line someone uncomments.
const SHARED = [
  '.gitattributes',
  '.github/workflows/ci.yml',
  '.github/workflows/deploy-dev.yml',
  '.github/workflows/deploy-prod.yml',
  '.github/workflows/deploy-stg.yml',
  '.github/workflows/deploy-test.yml',
  '.github/workflows/deploy.yml',
  '.gitignore.hbs',
  '.gitleaks.toml',
  'contracts/product-platform.v1.json',
  'Makefile.hbs',
  'apps/admin/src/app/api/auth/signout/route.ts.hbs',
  'apps/admin/src/app/api/auth/start/route.ts.hbs',
  'apps/admin/src/app/globals.css',
  'apps/admin/tsconfig.json',
  'eslint.config.mjs',
  'infrastructure/terraform/backend.tf.hbs',
  'infrastructure/terraform/providers.tf.hbs',
  'local/certs/.gitignore',
  'local/observability/loki.yml',
  'local/observability/otel-collector.yml',
  'local/observability/tempo.yml',
  'local/queue/redis.conf',
  'local/scripts/dev-app.mjs',
  'local/scripts/dev-service.mjs.hbs',
  'local/scripts/doppler-bootstrap.sh.hbs',
  'local/scripts/doppler-check.sh.hbs',
  'local/scripts/doppler_bootstrap_support.py',
  'local/scripts/migrate.sh',
  'local/scripts/reset.sh',
  'local/scripts/seed.sh.hbs',
  'local/zitadel/.gitignore',
  'local/zitadel/config.yaml',
  'local/zitadel/init.sh.hbs',
  'local/zitadel/machinekey/.gitignore',
  'packages/api-client/tsconfig.json',
  'packages/audit/package.json.hbs',
  'packages/audit/tsconfig.json',
  'packages/auth/package.json.hbs',
  'packages/auth/src/oauth.test.ts.hbs',
  'packages/auth/src/oauth.ts.hbs',
  'packages/auth/tsconfig.json',
  'packages/branding/package.json.hbs',
  'packages/branding/tsconfig.json',
  'packages/config/package.json.hbs',
  'packages/config/tsconfig.json',
  'packages/email/package.json.hbs',
  'packages/email/tsconfig.json',
  'packages/logger/package.json.hbs',
  'packages/logger/tsconfig.json',
  'packages/notifications/package.json.hbs',
  'packages/notifications/tsconfig.json',
  'packages/observability/package.json.hbs',
  'packages/observability/tsconfig.json',
  'packages/permissions/package.json.hbs',
  'packages/permissions/tsconfig.json',
  'packages/security/package.json.hbs',
  'packages/security/tsconfig.json',
  'packages/storage/package.json.hbs',
  'packages/storage/tsconfig.json',
  'packages/tenant/package.json.hbs',
  'packages/tenant/tsconfig.json',
  'packages/types/tsconfig.json',
  'packages/ui/package.json.hbs',
  'packages/ui/tsconfig.json',
  'packages/validation/package.json.hbs',
  'packages/validation/tsconfig.json',
  'pnpm-workspace.yaml',
  'python-packages/koras-audit/src/koras_audit/__init__.py',
  'python-packages/koras-audit/src/koras_audit/py.typed',
  'python-packages/koras-auth/pyproject.toml',
  'python-packages/koras-auth/src/koras_auth/py.typed',
  'python-packages/koras-database/pyproject.toml',
  'python-packages/koras-database/src/koras_database/__init__.py',
  'python-packages/koras-database/src/koras_database/py.typed',
  'python-packages/koras-logging/src/koras_logging/__init__.py',
  'python-packages/koras-logging/src/koras_logging/py.typed',
  'python-packages/koras-observability/src/koras_observability/__init__.py',
  'python-packages/koras-observability/src/koras_observability/py.typed',
  'python-packages/koras-platform/pyproject.toml',
  'python-packages/koras-platform/src/koras_platform/__init__.py',
  'python-packages/koras-platform/src/koras_platform/adapters.py',
  'python-packages/koras-platform/src/koras_platform/environment.py',
  'python-packages/koras-platform/src/koras_platform/py.typed',
  'python-packages/koras-platform/src/koras_platform/roles.py',
  'python-packages/koras-queue/src/koras_queue/__init__.py',
  'python-packages/koras-queue/src/koras_queue/py.typed',
  'python-packages/koras-storage/src/koras_storage/__init__.py',
  'python-packages/koras-storage/src/koras_storage/py.typed',
  'python-packages/koras-tenant/src/koras_tenant/py.typed',
  'services/api/fly.toml.hbs',
  'services/api/package.json.hbs',
  'services/api/koras_api/core/database.py',
  'services/api/koras_api/core/observability.py',
  'services/api/koras_api/routers/health.py',
  'services/scheduler/Dockerfile',
  'services/scheduler/fly.toml.hbs',
  'services/scheduler/package.json.hbs',
  'services/scheduler/pyproject.toml.hbs',
  'services/worker/Dockerfile',
  'services/worker/fly.toml.hbs',
  'services/worker/package.json.hbs',
  'services/worker/pyproject.toml.hbs',
  'services/worker/koras_worker/main.py',
  'supabase/seed/README.md',
  'tests/README.md',
  'tests/security/test_no_state_artifacts.py',
  'tests/security/test_settings_are_declared.py',
  'tests/unit/test_declared_dependencies.py',
  'tests/unit/test_scaffold.py',
  'tsconfig.base.json',
  'turbo.json',
]

/** Line endings are normalised: a checkout on Windows carries CRLF. */
function read(profile: string, file: string): string {
  const CR = String.fromCharCode(13)
  return readFileSync(join(PROFILES, profile, 'template', file), 'utf8').split(CR).join('')
}

describe('the two profiles do not drift apart', () => {
  it.each(SHARED)('%s is identical in both profiles', (file) => {
    expect(existsSync(join(PROFILES, 'product', 'template', file))).toBe(true)
    expect(existsSync(join(PROFILES, 'control-plane', 'template', file))).toBe(true)
    expect(read('control-plane', file)).toBe(read('product', file))
  })

  it('covers the files that are actually shared', () => {
    // Guards the guard. If the list were emptied or truncated, every assertion
    // above would still pass while checking nothing.
    expect(SHARED.length).toBeGreaterThanOrEqual(112)
  })
})
