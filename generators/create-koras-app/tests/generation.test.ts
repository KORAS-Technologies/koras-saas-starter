import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join, basename } from 'node:path'
import { rmSync, existsSync, readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { templatePath } from './template-path.js'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles, printDryRunManifest, toUnixLineEndings } from '../src/generation/writer.js'
import {
  PROJECT_MANIFEST_PATH,
  parseProjectManifest,
  renderProjectManifest,
  resolveTemplateDigest,
} from '../src/generation/project-manifest.js'
import { validateProfile } from '../src/validation/profile.js'
import { validateGeneratedProject } from '../src/validation/generated-project.js'

const OUT = join(tmpdir(), `koras-gen-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

interface Overrides {
  with?: string[]
  without?: string[]
}

function makeCtx(profile: ProfileName, slug: string, overrides: Overrides = {}, dryRun = false) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, overrides)
  validateSelections(manifest, selections)
  return buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun,
    provision: false,
  })
}

async function generate(profile: ProfileName, slug: string, overrides: Overrides = {}) {
  const ctx = makeCtx(profile, slug, overrides)
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  return {
    fileList,
    has: (prefix: string) => fileList.some((f) => f === prefix || f.startsWith(`${prefix}/`)),
    read: (relPath: string) => readFileSync(join(OUT, slug, relPath), 'utf8'),
  }
}

// ── dry run ──────────────────────────────────────────────────────────────────

describe('dry run', () => {
  it('lists files without writing any', async () => {
    const ctx = makeCtx('product', 'dry-run-app', {}, true)
    const result = await writeFiles(ctx, renderTemplate(ctx))
    expect(result.filesWritten).toBe(0)
    expect(result.fileList.length).toBeGreaterThan(10)
    expect(existsSync(join(OUT, 'dry-run-app'))).toBe(false)
  })
})

// ── product profile ──────────────────────────────────────────────────────────

describe('generate product', () => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('product', 'sampleapp')
  })

  it('generates required apps and services', () => {
    expect(gen.has('apps/web')).toBe(true)
    expect(gen.has('services/api')).toBe(true)
  })

  it('honours profile defaults for optional components', () => {
    expect(gen.has('apps/admin')).toBe(true) // default: true
    expect(gen.has('services/worker')).toBe(true) // default: true
    expect(gen.has('apps/marketing')).toBe(false) // default: false
    expect(gen.has('services/scheduler')).toBe(false) // default: false
    expect(gen.has('services/ai-gateway')).toBe(false) // default: false
  })

  it('does not generate control-plane applications', () => {
    expect(gen.has('apps/portal')).toBe(false)
  })

  /**
   * Removed 2026-08-30, F4. `packages/control-plane-client` was generated into
   * every product, compiled, shipped, and imported by nothing -- confirmed on a
   * real generated estate, not just the templates. Its payload type could not
   * produce a request the Control Plane accepts: every field was either missing
   * from `ProductRegistrationRequest` or rejected by `extra="forbid"`, so the
   * first caller to trust it would have got a 422 reading like an auth failure.
   *
   * Registration is performed by the generator's own `src/registration/` and by
   * `register-with-control-plane.sh`. Neither could have imported this package:
   * one lives in the factory, the other is bash. And the contract has exactly
   * one outbound direction, so there was no second caller coming.
   *
   * Asserted as absent rather than deleted silently, because a package that
   * reappears is how the outbound and inbound halves get conflated again.
   */
  it('generates no Control Plane client package', () => {
    expect(gen.has('packages/control-plane-client')).toBe(false)
  })

  /**
   * What the package's removal must not take with it. The capability gated the
   * package *and* these two settings -- one flag doing two unrelated jobs -- so
   * dropping it without ungating them would have left every product unable to
   * declare what its own deploy-time registration reads.
   */
  it('still declares the two Control Plane settings registration reads', () => {
    const manifest = gen.read('local/config/secrets.manifest')
    expect(manifest).toContain('KORAS_CONTROL_PLANE_URL optional')
    expect(manifest).toContain('KORAS_CONTROL_PLANE_TOKEN optional')
    expect(gen.read('local/config/.env.local.example')).toContain('KORAS_CONTROL_PLANE_URL=')
  })

  it('renders the slug into package.json', () => {
    expect(gen.read('package.json')).toContain('sampleapp')
  })
})

describe('product optional components', () => {
  it('can enable marketing and the AI Gateway', async () => {
    const gen = await generate('product', 'sampleapp-full', { with: ['marketing', 'ai_gateway'] })
    expect(gen.has('apps/marketing')).toBe(true)
    expect(gen.has('services/ai-gateway')).toBe(true)
  })

  it('can disable optional components without losing required ones', async () => {
    const gen = await generate('product', 'sampleapp-min', { without: ['admin', 'worker'] })
    expect(gen.has('apps/admin')).toBe(false)
    expect(gen.has('services/worker')).toBe(false)
    expect(gen.has('apps/web')).toBe(true)
    expect(gen.has('services/api')).toBe(true)
  })

  it('applies the capability matrix to template selection', async () => {
    const gen = await generate('product', 'sampleapp-nobilling', { without: ['billing'] })
    expect(gen.has('packages/billing')).toBe(false)
    expect(gen.has('packages/domains')).toBe(true) // custom_domains still enabled
  })

  it('rejects an unknown component with an actionable error', async () => {
    await expect(generate('product', 'sampleapp-bad', { with: ['nope'] })).rejects.toThrow(
      /Unknown component "nope".*Known components/s,
    )
  })

  it('rejects disabling a required component', async () => {
    await expect(generate('product', 'sampleapp-noapi', { without: ['api'] })).rejects.toThrow(
      /Service "api" is required/,
    )
  })
})

// ── the ai capability ────────────────────────────────────────────────────────

describe('the ai capability', () => {
  /**
   * Off by default, and off means absent: a product that did not ask for an
   * assistant carries no router, no page, no migration and no test for it.
   * The framework package ships regardless -- it is a library nothing imports
   * -- and so do the components and the translations, which are inert.
   */
  it('generates none of the assistant by default', async () => {
    const gen = await generate('product', 'sampleapp-noai')
    expect(gen.has('services/api/koras_api/routers/ai.py')).toBe(false)
    expect(gen.has('services/api/koras_api/core/ai.py')).toBe(false)
    expect(gen.has('services/api/koras_api/ai')).toBe(false)
    expect(gen.has('supabase/migrations/00006_ai.sql')).toBe(false)
    expect(gen.has('supabase/tests/060_ai_isolation.sql')).toBe(false)
    expect(gen.has('apps/web/src/app/dashboard/assistant')).toBe(false)
    expect(gen.has('e2e/assistant.spec.ts')).toBe(false)
    expect(gen.has('tests/unit/test_ai_api.py')).toBe(false)
    expect(gen.has('python-packages/koras-ai')).toBe(true)
    expect(gen.read('services/api/koras_api/main.py')).not.toContain('ai.router')
    expect(gen.read('services/api/koras_api/core/settings.py')).not.toContain('ai_gateway_url')
    expect(gen.read('services/api/pyproject.toml')).not.toContain('koras-ai')
    expect(gen.read('packages/branding/src/index.ts')).not.toContain("id: 'assistant'")
    expect(gen.read('apps/web/src/app/dashboard/layout.tsx')).not.toContain('AssistantLauncher')
  })

  it('refuses the capability without the gateway it needs', async () => {
    await expect(generate('product', 'sampleapp-ai-alone', { with: ['ai'] })).rejects.toThrow(
      /Component "ai" requires "ai_gateway".*--with ai,ai_gateway/s,
    )
  })

  it('generates the whole assistant with the gateway', async () => {
    const gen = await generate('product', 'sampleapp-ai', { with: ['ai', 'ai_gateway'] })
    for (const path of [
      'services/api/koras_api/routers/ai.py',
      'services/api/koras_api/core/ai.py',
      'services/api/koras_api/ai/__init__.py',
      'services/api/koras_api/ai/agents.py',
      'services/api/koras_api/ai/tools.py',
      'services/api/koras_api/ai/prompts.py',
      'services/api/koras_api/ai/knowledge.py',
      'services/api/koras_api/ai/models.py',
      'supabase/migrations/00006_ai.sql',
      'supabase/tests/060_ai_isolation.sql',
      'apps/web/src/app/dashboard/assistant/page.tsx',
      'apps/web/src/app/dashboard/assistant/actions.ts',
      'e2e/assistant.spec.ts',
      'tests/unit/test_ai_api.py',
      'services/ai-gateway/litellm_config.yaml',
    ]) {
      expect(gen.has(path), `${path} missing`).toBe(true)
    }
    expect(gen.read('services/api/koras_api/main.py')).toContain('ai.router')
    expect(gen.read('services/api/koras_api/core/settings.py')).toContain('ai_gateway_url')
    expect(gen.read('services/api/pyproject.toml')).toContain('koras-ai = { workspace = true }')
    expect(gen.read('packages/branding/src/index.ts')).toContain("id: 'assistant'")
    expect(gen.read('apps/web/src/app/dashboard/layout.tsx')).toContain('AssistantLauncher')
    // Recorded, so a later --check-drift or --refresh knows what this project has.
    expect(gen.read(PROJECT_MANIFEST_PATH)).toMatch(/capabilities:[\s\S]*- ai\n/)
    // No provider key, no provider model, no secret anywhere the generator wrote.
    expect(gen.read('services/api/koras_api/ai/models.py')).not.toMatch(/sk-|openai\/|anthropic\//)
    expect(gen.read('local/config/secrets.manifest')).toContain('AI_GATEWAY_URL derived')
  })
})

// ── capability leakage, derived rather than listed ───────────────────────────

/**
 * A file generated into a product must not import something the product does
 * not have.
 *
 * The two tests above name the paths a product without `ai` or without
 * `reporting` must not carry, and each is a list written by hand. A list is
 * correct on the day it is written and has no way of noticing the world moved:
 * `tests/unit/test_ai_turn_quota.py` arrived with the per-minute ceiling on
 * 2026-09-15, nobody added it to the manifest's `template_map` or to the list
 * above, and it shipped into every product generated without an assistant --
 * where it fails at import, because `koras_api.core.ai` is not there. That is
 * the third capability leak in two days and the second found by CI rather than
 * here.
 *
 * So this one is derived from a source that cannot drift: the template tree
 * itself. If a module exists in the templates, is absent from this generated
 * project, and some file that *is* in this project imports it, the manifest
 * gated one and not the other. It needs no list and cannot go stale -- a
 * capability added tomorrow is covered by having been written.
 */
describe('nothing generated imports what was not generated', () => {
  /**
   * Whether a path exists in either template layer, without throwing.
   *
   * `templatePath` raises when it finds nothing, which is right for a test
   * reading a file it expects and wrong here: not finding it is the answer
   * this asks for.
   */
  const TEMPLATES = join(__dirname, '..', '..', '..', 'profiles')
  function inTemplateTree(relative: string): boolean {
    const segments = relative.split('/')
    return (
      existsSync(join(TEMPLATES, 'product', 'template', ...segments)) ||
      existsSync(join(TEMPLATES, '_shared', 'template', ...segments)) ||
      existsSync(join(TEMPLATES, 'product', 'template', `${relative}.hbs`.split('/').join('/'))) ||
      existsSync(join(TEMPLATES, '_shared', 'template', `${relative}.hbs`.split('/').join('/')))
    )
  }

  /** `koras_api.core.ai` -> the paths a module of that name could occupy. */
  function candidates(module: string): string[] {
    const relative = module.split('.').slice(1).join('/')
    if (relative === '') return []
    return [
      `services/api/koras_api/${relative}.py`,
      `services/api/koras_api/${relative}/__init__.py`,
    ]
  }

  /**
   * Every `koras_api` module a Python file refers to.
   *
   * Both spellings, because the leak used the second: `import koras_api.core.ai`
   * names the module, and `from koras_api.core import ai` names the package and
   * leaves the module in the import list -- which reads as a symbol and is a
   * file on disk.
   */
  function imported(source: string): string[] {
    const found = new Set<string>()
    for (const [, module] of source.matchAll(/^\s*import\s+(koras_api[\w.]*)/gm)) {
      found.add(module)
    }
    for (const [, pkg, names] of source.matchAll(
      /^\s*from\s+(koras_api[\w.]*)\s+import\s+([^\n(]+|\([^)]*\))/gm,
    )) {
      found.add(pkg)
      for (const raw of names.replace(/[()]/g, '').split(',')) {
        const name = raw.trim().split(/\s+as\s+/)[0]?.trim()
        if (name && /^[a-z_][\w]*$/.test(name)) found.add(`${pkg}.${name}`)
      }
    }
    return [...found]
  }

  it.each([
    ['sampleapp-leak-default', {}],
    ['sampleapp-leak-minimal', { without: ['admin', 'worker', 'reporting'] }],
    ['sampleapp-leak-ai', { with: ['ai', 'ai_gateway'] }],
    // Without the two governance capabilities, which between them remove three
    // worker sweeps, three routers and two core modules. The row exists because
    // every capability added since this test was written has leaked at least
    // once, and the leak is always a test file nobody remembered to gate.
    ['sampleapp-leak-governance', { without: ['audit_governance', 'storage_governance'] }],
  ] as Array<[string, Overrides]>)('in a product generated as %s', async (slug, overrides) => {
    const gen = await generate('product', slug, overrides)
    const generated = new Set(gen.fileList)
    const offences: string[] = []

    for (const file of gen.fileList) {
      if (!file.endsWith('.py')) continue
      if (!file.startsWith('services/') && !file.startsWith('tests/')) continue

      for (const module of imported(gen.read(file))) {
        const options = candidates(module)
        if (options.length === 0) continue
        // Present here: nothing to say.
        if (options.some((candidate) => generated.has(candidate))) continue
        // Absent here and absent from the templates too: not a module at all,
        // but a symbol defined inside one. Only the templates can tell the
        // difference, and only their answer makes this a leak.
        if (options.some(inTemplateTree)) offences.push(`${file} imports ${module}`)
      }
    }

    expect(
      offences.sort(),
      'These files were generated into a product that does not carry what they ' +
        'import, so a capability gated one and not the other. Add the importing ' +
        "file to the same entry of the manifest's `template_map`.",
    ).toEqual([])
  })

  it('catches a leak, given one', async () => {
    // The mutation: the check is only worth having if an ungated file that
    // imports a gated module fails it. `test_ai_turn_quota.py` is the real
    // one, so the template's own gating is what this asserts -- remove it from
    // `template_map` and the case above fails rather than this one.
    const gated = readFileSync(join(__dirname, '..', '..', '..', 'profiles', 'product', 'manifest.yaml'), 'utf8')
    expect(gated).toContain('tests/unit/test_ai_turn_quota.py')
    expect(inTemplateTree('services/api/koras_api/core/ai.py')).toBe(true)
  })
})

// ── the reporting capability ─────────────────────────────────────────────────

describe('the reporting capability', () => {
  /**
   * On by default, and off means absent: a product generated without it
   * carries no router, no pages and no test for them. The audit table is
   * not among them since 2026-09-15: it is foundation, and reporting is one
   * of the modules that records to it.
   * The framework package ships regardless, as `koras-ai` does, and so do
   * the components and the translations, which are inert.
   */
  it('generates analytics by default', async () => {
    const gen = await generate('product', 'sampleapp-reporting')
    for (const path of [
      'services/api/koras_api/routers/reporting.py',
      'services/api/koras_api/core/reporting.py',
      'services/api/koras_api/reporting/__init__.py',
      'services/api/koras_api/reporting/standard.py',
      'services/api/koras_api/reporting/reports.py',
      'apps/web/src/app/dashboard/analytics/page.tsx',
      'apps/web/src/app/dashboard/analytics/[report]/page.tsx',
      'apps/web/src/app/api/reports/[key]/export/route.ts',
      'e2e/analytics.spec.ts',
      'tests/unit/test_reporting_api.py',
      'python-packages/koras-reporting/pyproject.toml',
      // The second wave: schedules and background exports, the activity
      // contract for the platform, and the worker that delivers.
      'services/api/koras_api/routers/reporting_schedules.py',
      'services/api/koras_api/routers/platform_reporting.py',
      'supabase/migrations/00014_report_schedules.sql',
      'supabase/tests/130_report_schedules_isolation.sql',
      'apps/web/src/app/dashboard/analytics/actions.ts',
      'apps/web/src/app/api/reports/exports/[id]/download/route.ts',
      'tests/unit/test_reporting_schedules.py',
      'tests/unit/test_reporting_delivery.py',
      'tests/unit/test_platform_activity.py',
      'supabase/migrations/00015_tenant_plans.sql',
      'supabase/tests/150_tenant_plans_isolation.sql',
      'tests/unit/test_platform_plan.py',
    ]) {
      expect(gen.has(path), `${path} missing`).toBe(true)
    }
    expect(gen.read('services/api/koras_api/main.py')).toContain('reporting.router')
    expect(gen.read('services/api/koras_api/main.py')).toContain('reporting_schedules.router')
    expect(gen.read('services/worker/koras_worker/worker.py')).toContain('deliver_scheduled_reports')
    // The worker image carries the API's catalogue package, and only that.
    const dockerfile = gen.read('services/worker/Dockerfile')
    expect(dockerfile).toContain('COPY services/api/koras_api/reporting/')
    expect(dockerfile).toContain('PYTHONPATH=/app/services/api')
    expect(gen.read('services/worker/pyproject.toml')).toContain('koras-reporting')
    expect(gen.read('local/config/secrets.manifest')).toContain('REPORT_EXPORT_RETENTION_DAYS')
    expect(gen.read('services/api/pyproject.toml')).toContain('koras-reporting = { workspace = true }')
    expect(gen.read('packages/branding/src/index.ts')).toContain("id: 'analytics'")
    expect(gen.read(PROJECT_MANIFEST_PATH)).toMatch(/capabilities:[\s\S]*- reporting\n/)
    // The generated capability list the API reads agrees with the registry's.
    expect(gen.read('services/api/koras_api/core/reporting.py')).toContain('"reporting",')
  })

  it('generates none of it without the capability, and the rest still stands', async () => {
    const gen = await generate('product', 'sampleapp-noreporting', { without: ['reporting'] })
    expect(gen.has('services/api/koras_api/routers/reporting.py')).toBe(false)
    expect(gen.has('services/api/koras_api/core/reporting.py')).toBe(false)
    expect(gen.has('services/api/koras_api/reporting')).toBe(false)
    expect(gen.has('apps/web/src/app/dashboard/analytics')).toBe(false)
    expect(gen.has('apps/web/src/app/api/reports')).toBe(false)
    expect(gen.has('e2e/analytics.spec.ts')).toBe(false)
    expect(gen.has('tests/unit/test_reporting_api.py')).toBe(false)
    expect(gen.has('python-packages/koras-reporting')).toBe(true)
    expect(gen.read('services/api/koras_api/main.py')).not.toContain('reporting.router')
    expect(gen.read('services/api/pyproject.toml')).not.toContain('koras-reporting')
    expect(gen.read('packages/branding/src/index.ts')).not.toContain("id: 'analytics'")
    // The audit table is foundation: a product without reporting still
    // records, still sweeps, and still declares the setting that governs it.
    expect(gen.has('supabase/migrations/00013_audit_events.sql')).toBe(true)
    expect(gen.has('supabase/tests/110_audit_isolation.sql')).toBe(true)
    expect(gen.has('services/api/koras_api/core/audit.py')).toBe(true)
    expect(gen.has('services/worker/koras_worker/tasks/audit_retention.py')).toBe(true)
    expect(gen.has('tests/unit/test_audit_retention.py')).toBe(true)
    expect(gen.read('services/worker/koras_worker/worker.py')).toContain('purge_audit_history')
    expect(gen.read('services/worker/koras_worker/worker.py')).toContain('from arq import cron')
    expect(gen.read('local/config/secrets.manifest')).toContain('AUDIT_RETENTION_DAYS')
    expect(gen.read('local/config/secrets.manifest')).not.toContain('REPORT_EXPORT_RETENTION_DAYS')
    expect(gen.has('supabase/migrations/00014_report_schedules.sql')).toBe(false)
    // The plan snapshot is the contract's, not reporting's: it stays.
    expect(gen.has('supabase/migrations/00015_tenant_plans.sql')).toBe(true)
    expect(gen.read('services/api/koras_api/routers/platform.py')).toContain('/tenants/{tenant_id}/plan')
    expect(gen.read('services/worker/Dockerfile')).not.toContain('koras_api')
    expect(gen.read('services/worker/pyproject.toml')).not.toContain('koras-reporting')
  })
})

// ── control-plane profile ────────────────────────────────────────────────────

describe('generate control-plane', () => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate('control-plane', 'koras-control-plane')
  })

  it('generates platform admin and customer portal', () => {
    expect(gen.has('apps/admin')).toBe(true)
    expect(gen.has('apps/portal')).toBe(true)
  })

  it('generates api, worker, and scheduler', () => {
    expect(gen.has('services/api')).toBe(true)
    expect(gen.has('services/worker')).toBe(true)
    expect(gen.has('services/scheduler')).toBe(true)
  })

  it('does not generate product-only applications', () => {
    expect(gen.has('apps/web')).toBe(false)
    expect(gen.has('apps/marketing')).toBe(false)
  })

  it('excludes the AI Gateway by default', () => {
    expect(gen.has('services/ai-gateway')).toBe(false)
  })

  it('does not include a Control Plane client', () => {
    expect(gen.has('packages/control-plane-client')).toBe(false)
  })

  it('generates the product registry router', () => {
    expect(gen.has('services/api/koras_api/routers/products.py')).toBe(true)
  })
})

// ── profile propagation into generated files ─────────────────────────────────

describe('profile propagation', () => {
  const cases: Array<[ProfileName, string]> = [
    ['product', 'prop-product'],
    ['control-plane', 'prop-cp'],
  ]

  for (const [profile, slug] of cases) {
    describe(profile, () => {
      let gen: Awaited<ReturnType<typeof generate>>
      beforeAll(async () => {
        gen = await generate(profile, slug)
      })

      it('writes the profile into CLAUDE.md', () => {
        expect(gen.read('CLAUDE.md')).toContain(`Profile: \`${profile}\``)
      })

      it('writes the profile into README.md', () => {
        expect(gen.read('README.md')).toContain(`| **Profile** | \`${profile}\` |`)
      })

      it('writes the profile into the Makefile', () => {
        expect(gen.read('Makefile')).toContain(`PROFILE := ${profile}`)
      })

      it('writes the profile into .koras/project.yaml', () => {
        const manifest = parseProjectManifest(gen.read(PROJECT_MANIFEST_PATH), 'test')
        expect(manifest.project.profile).toBe(profile)
        expect(manifest.project.slug).toBe(slug)
      })

      it('writes the profile into terraform.tfvars', () => {
        const tfvars = gen.read('infrastructure/terraform/terraform.tfvars')
        expect(tfvars).toContain(`profile      = "${profile}"`)
        expect(tfvars).toContain(`project_slug = "${slug}"`)
      })

      it('keeps secrets out of the committed tfvars', () => {
        // Comments document which TF_VAR_* carries each secret, so assert on
        // the assignments only.
        const assignments = gen
          .read('infrastructure/terraform/terraform.tfvars')
          .split('\n')
          .filter((line) => !line.trimStart().startsWith('#'))
          .join('\n')
        for (const secret of ['db_password', 'jwt_profile_json', 'token']) {
          expect(assignments).not.toContain(secret)
        }
        // ...and the generated .gitignore must not exclude the file itself
        expect(gen.read('.gitignore')).toContain('!infrastructure/terraform/terraform.tfvars')
      })

      it('renders Terraform enabled_apps and enabled_services from selections', () => {
        const tfvars = gen.read('infrastructure/terraform/terraform.tfvars')
        const apps = JSON.parse(/enabled_apps\s+= (\[.*\])/.exec(tfvars)![1]) as string[]
        const services = JSON.parse(/enabled_services = (\[.*\])/.exec(tfvars)![1]) as string[]
        expect(apps.length).toBeGreaterThan(0)
        expect(services).toContain('api')
        if (profile === 'control-plane') {
          expect(services).not.toContain('ai_gateway')
        }
      })
    })
  }

  it('excludes deselected services from Terraform inputs', async () => {
    const gen = await generate('product', 'prop-tf-min', { without: ['worker'] })
    const tfvars = gen.read('infrastructure/terraform/terraform.tfvars')
    const services = JSON.parse(/enabled_services = (\[.*\])/.exec(tfvars)![1]) as string[]
    expect(services).toContain('api')
    expect(services).not.toContain('worker')
  })
})

// ── line endings ─────────────────────────────────────────────────────────────

describe('line endings', () => {
  it('writes shell scripts, Makefiles, and Dockerfiles with LF', async () => {
    // On Windows with core.autocrlf=true the templates themselves carry CRLF,
    // and copying those bytes verbatim gives a project whose `make bootstrap`
    // dies on `set -euo pipefail\r: invalid option name`.
    for (const [profile, slug] of [
      ['product', 'eol-product'],
      ['control-plane', 'eol-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      const shellFiles = gen.fileList.filter(
        (f) => /\.(sh|bash|mk)$/.test(f) || /(^|\/)(Makefile|Dockerfile)$/.test(f),
      )
      expect(shellFiles.length).toBeGreaterThan(0)
      for (const file of shellFiles) {
        expect(readFileSync(join(OUT, slug, file), 'utf8')).not.toContain('\r\n')
      }
    }
  })

  it('normalizes CRLF regardless of the source encoding', () => {
    expect(toUnixLineEndings('a\r\nb\r\n')).toBe('a\nb\n')
    expect(toUnixLineEndings(Buffer.from('a\r\nb')).toString()).toBe('a\nb')
    // A lone CR is data, not a line ending.
    expect(toUnixLineEndings('a\rb')).toBe('a\rb')
  })

  it('generates a .gitattributes that pins them for later checkouts', async () => {
    const gen = await generate('product', 'eol-attributes')
    expect(gen.has('.gitattributes')).toBe(true)
    const attributes = gen.read('.gitattributes')
    expect(attributes).toContain('*.sh        text eol=lf')
    // Windows-native scripts must keep CRLF — cmd.exe requires it.
    expect(attributes).toContain('*.bat       text eol=crlf')
  })
})

// ── generated project manifest (.koras/project.yaml) ─────────────────────────

describe('generated project manifest', () => {
  const starterVersion = JSON.parse(
    readFileSync(join(process.cwd(), '../../package.json'), 'utf8'),
  ).version as string

  describe('product profile', () => {
    let gen: Awaited<ReturnType<typeof generate>>
    beforeAll(async () => {
      gen = await generate('product', 'docoris')
    })

    it('generates the manifest at the canonical path', () => {
      expect(gen.has(PROJECT_MANIFEST_PATH)).toBe(true)
      expect(existsSync(join(OUT, 'docoris', '.koras', 'project.yaml'))).toBe(true)
    })

    it('records the project identity and profile', () => {
      const manifest = parseProjectManifest(gen.read(PROJECT_MANIFEST_PATH), 'test')
      expect(manifest.schema_version).toBe(1)
      expect(manifest.project.slug).toBe('docoris')
      expect(manifest.project.profile).toBe('product')
      expect(manifest.generator.name).toBe('create-koras-app')
    })

    it('resolves versions from starter and profile metadata', () => {
      const manifest = parseProjectManifest(gen.read(PROJECT_MANIFEST_PATH), 'test')
      expect(manifest.generator.starter_version).toBe(starterVersion)
      expect(manifest.generator.profile_version).toBe(loadProfile('product').manifest.version)
    })

    it('never emits a placeholder version', () => {
      const raw = gen.read(PROJECT_MANIFEST_PATH)
      for (const placeholder of ['TBD', 'latest', 'unknown', '...']) {
        expect(raw).not.toContain(placeholder)
      }
    })
  })

  describe('control-plane profile', () => {
    let gen: Awaited<ReturnType<typeof generate>>
    beforeAll(async () => {
      gen = await generate('control-plane', 'koras-control-plane')
    })

    it('records the control-plane identity', () => {
      const manifest = parseProjectManifest(gen.read(PROJECT_MANIFEST_PATH), 'test')
      expect(manifest).toEqual({
        schema_version: 1,
        project: {
          name: 'koras-control-plane',
          slug: 'koras-control-plane',
          profile: 'control-plane',
        },
        generator: {
          name: 'create-koras-app',
          starter_version: starterVersion,
          profile_version: loadProfile('control-plane').manifest.version,
          // Recomputed rather than hardcoded: pinning the digest here would
          // mean editing this assertion on every template change, which is a
          // test that gets updated reflexively rather than read.
          template_digest: resolveTemplateDigest('control-plane'),
        },
        components: {
          applications: ['platform_admin', 'portal'],
          services: ['api', 'scheduler', 'worker'],
          // Derived the same way the generator does, so the assertion tracks
          // the profile rather than a copy of it made today.
          capabilities: Object.entries(
            resolveSelections(
              loadProfile('control-plane').manifest,
              loadProfile('control-plane').defaults,
            ).capabilities,
          )
            .filter(([, on]) => on)
            .map(([name]) => name)
            .sort(),
        },
      })
    })

    // Control Plane tooling gates on this field before running platform-only
    // provisioning; `product` here would be a silent, dangerous misroute.
    it('never records the product profile', () => {
      const raw = gen.read(PROJECT_MANIFEST_PATH)
      expect(raw).not.toMatch(/profile:\s*product/)
      expect(raw).toMatch(/profile:\s*control-plane/)
    })
  })

  it('serializes deterministically, in the declared field order', () => {
    const ctx = makeCtx('product', 'determinism-app')
    const first = renderProjectManifest(ctx)
    const second = renderProjectManifest(ctx)
    expect(first).toBe(second)
    const keyOrder = [...first.matchAll(/^(\w+):/gm)].map((m) => m[1])
    expect(keyOrder).toEqual(['schema_version', 'project', 'generator', 'components'])
    const projectKeys = [...first.matchAll(/^ {2}(\w+):/gm)].map((m) => m[1])
    expect(projectKeys).toEqual([
      'name',
      'slug',
      'profile',
      'name',
      'starter_version',
      'profile_version',
      'template_digest',
      'applications',
      'services',
      'capabilities',
    ])
  })

  it('carries no secrets', async () => {
    // The header comment says the file holds no secrets; assert on the data.
    const data = (await generate('product', 'manifest-clean'))
      .read(PROJECT_MANIFEST_PATH)
      .split('\n')
      .filter((line) => !line.trimStart().startsWith('#'))
      .join('\n')
      .toLowerCase()
    for (const secret of ['token', 'password', 'jwt_profile', 'secret', 'key', 'credential']) {
      expect(data).not.toContain(secret)
    }
  })

  it('refuses to build a manifest for an unsupported profile', () => {
    const ctx = { ...makeCtx('product', 'bad-profile-app'), profile: 'invalid-profile' as ProfileName }
    expect(() => renderProjectManifest(ctx)).toThrow(
      /unsupported profile "invalid-profile".*Supported profiles/s,
    )
  })

  it('refuses a profile version that is not semver', () => {
    const ctx = makeCtx('product', 'bad-version-app')
    const broken = { ...ctx, manifest: { ...ctx.manifest, version: 'latest' } }
    expect(() => renderProjectManifest(broken)).toThrow(/not a semantic version/)
  })

  it('is reported by --dry-run without being written', async () => {
    const ctx = makeCtx('product', 'dry-run-manifest', {}, true)
    const files = renderTemplate(ctx)
    const result = await writeFiles(ctx, files)
    expect(result.fileList).toContain(PROJECT_MANIFEST_PATH)
    expect(result.filesWritten).toBe(0)
    expect(existsSync(join(OUT, 'dry-run-manifest'))).toBe(false)

    // Named in the dry-run header, and listed in sorted order rather than
    // buried at the end of ~180 template-walk-ordered paths.
    const lines: string[] = []
    const log = console.log
    console.log = (msg?: unknown) => void lines.push(String(msg))
    try {
      printDryRunManifest(ctx, files)
    } finally {
      console.log = log
    }
    const output = lines.join('\n')
    expect(output).toContain(`Manifest: dry-run-manifest/${PROJECT_MANIFEST_PATH}`)
    expect(output).toContain(`  dry-run-manifest/${PROJECT_MANIFEST_PATH}`)

    const listed = lines
      .filter((l) => l.startsWith('  dry-run-manifest/'))
      .map((l) => l.trim().replace('dry-run-manifest/', ''))
    expect(listed).toEqual([...listed].sort())
    // ...which puts it among the other dotfiles, not after infrastructure/
    expect(listed.indexOf(PROJECT_MANIFEST_PATH)).toBeLessThan(listed.indexOf('package.json'))
  })
})

// ── dry-run messaging ────────────────────────────────────────────────────────

describe('dry-run closing message', () => {
  function capture(ctx: ReturnType<typeof makeCtx>): string {
    const lines: string[] = []
    const log = console.log
    console.log = (msg?: unknown) => void lines.push(String(msg))
    try {
      printDryRunManifest(ctx, renderTemplate(ctx))
    } finally {
      console.log = log
    }
    return lines.join('\n')
  }

  it('says nothing was written for a plain dry run', () => {
    const output = capture(makeCtx('product', 'msg-plain', {}, true))
    expect(output).toContain('No files were written')
  })

  it('does not claim nothing was written when --provision wrote the project', () => {
    // `--provision --dry-run` writes the source: Terraform can only plan a
    // configuration that exists. The old closing line contradicted the
    // "Generated N files" line printed straight after it.
    const ctx = { ...makeCtx('product', 'msg-provision', {}, true), provision: true }
    const output = capture(ctx)
    expect(output).not.toContain('No files were written')
    expect(output).toContain('IS written to disk')
    expect(output).toContain('No infrastructure is created')
  })
})

// ── generated project validation ─────────────────────────────────────────────

describe('generated project validation', () => {
  it('accepts a freshly generated project of either profile', async () => {
    for (const [profile, slug] of [
      ['product', 'valid-product'],
      ['control-plane', 'valid-cp'],
    ] as Array<[ProfileName, string]>) {
      await generate(profile, slug)
      const check = validateGeneratedProject({
        projectRoot: join(OUT, slug),
        expectedSlug: slug,
        expectedProfile: profile,
      })
      expect(check.valid).toBe(true)
      expect(check.manifest!.project.profile).toBe(profile)
    }
  })

  it('fails when the manifest is missing', async () => {
    const slug = 'missing-manifest'
    await generate('product', slug)
    rmSync(join(OUT, slug, '.koras', 'project.yaml'))
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/has no \.koras\/project\.yaml/)
  })

  it('fails when the manifest is not valid YAML', async () => {
    const slug = 'broken-manifest'
    await generate('product', slug)
    writeFileSync(join(OUT, slug, '.koras', 'project.yaml'), 'project: [unclosed\n')
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/not valid YAML/)
  })

  it('fails when the manifest schema version is unsupported', async () => {
    const slug = 'future-manifest'
    await generate('product', slug)
    const path = join(OUT, slug, '.koras', 'project.yaml')
    writeFileSync(path, readFileSync(path, 'utf8').replace('schema_version: 1', 'schema_version: 2'))
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/schema_version/)
  })

  it('fails when the recorded profile is not the requested one', async () => {
    const slug = 'profile-drift'
    await generate('control-plane', slug)
    const path = join(OUT, slug, '.koras', 'project.yaml')
    writeFileSync(path, readFileSync(path, 'utf8').replace('control-plane', 'product'))
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'control-plane',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/records profile "product"/)
  })

  it('fails when the recorded slug is not the requested one', async () => {
    const slug = 'slug-drift'
    await generate('product', slug)
    const path = join(OUT, slug, '.koras', 'project.yaml')
    writeFileSync(path, readFileSync(path, 'utf8').replace(/slug: .*/, 'slug: somethingelse'))
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/records slug "somethingelse"/)
  })
})

// ── generated project actually installs ──────────────────────────────────────

describe('the generated project can install its dependencies', () => {
  // `services/*` is a uv workspace glob, so a service without a pyproject.toml
  // fails `uv sync` for the whole project — which is step one of
  // `make bootstrap`, before anything else can be tried.
  it('gives every Python service a pyproject.toml', async () => {
    // Enable every service the profile actually has — the AI Gateway exists
    // only for product, and an unknown component is rejected outright.
    const cases: Array<[ProfileName, string, string[]]> = [
      ['product', 'install-product', ['worker', 'scheduler', 'ai_gateway']],
      ['control-plane', 'install-cp', ['worker', 'scheduler']],
    ]
    for (const [profile, slug, enabled] of cases) {
      const gen = await generate(profile, slug, { with: enabled })
      const services = new Set(
        gen.fileList
          .filter((f) => f.startsWith('services/'))
          .map((f) => f.split('/')[1]),
      )
      expect(services.size).toBeGreaterThan(1)
      for (const service of services) {
        expect(gen.fileList).toContain(`services/${service}/pyproject.toml`)
      }
    }
  })

  it('names each service package after the project', async () => {
    const gen = await generate('control-plane', 'install-names')
    expect(gen.read('services/worker/pyproject.toml')).toContain('name = "install-names-worker"')
    expect(gen.read('services/api/pyproject.toml')).toContain('name = "install-names-api"')
  })

  // The template scripts were copied from the starter, which splits its compose
  // file into shared/product/control-plane and layers them. A generated project
  // has one rendered file, so those paths never resolved.
  it('points its scripts at the compose file it actually has', async () => {
    for (const [profile, slug] of [
      ['product', 'compose-product'],
      ['control-plane', 'compose-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      for (const script of ['bootstrap.sh', 'reset.sh']) {
        const contents = gen.read(`local/scripts/${script}`)
        expect(contents).toContain('local/docker-compose.yml')
        expect(contents).not.toContain('local/docker/')
      }
      expect(gen.has('local/docker-compose.yml')).toBe(true)
    }
  })
})

// ── shared assets ────────────────────────────────────────────────────────────

describe('shared assets', () => {
  it('bundles the Terraform modules into both profiles', async () => {
    for (const [profile, slug] of [
      ['product', 'assets-product'],
      ['control-plane', 'assets-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      for (const mod of ['project-bootstrap', 'github', 'doppler', 'supabase', 'zitadel']) {
        expect(gen.has(`infrastructure/terraform/modules/${mod}`)).toBe(true)
      }
      // the root module resolves the bundled copy, not a path outside the project
      expect(gen.read('infrastructure/terraform/main.tf')).toContain(
        'source = "./modules/project-bootstrap"',
      )
    }
  })

  it('copies shared assets verbatim, without Handlebars rendering', async () => {
    const gen = await generate('product', 'assets-verbatim')
    const generated = gen.read('infrastructure/terraform/modules/zitadel/main.tf')
    const source = readFileSync(
      join(process.cwd(), '../../infrastructure/terraform/modules/zitadel/main.tf'),
      'utf8',
    )
    expect(generated).toBe(source)
  })
})

// ── infrastructure naming ────────────────────────────────────────────────────

describe('infrastructure naming', () => {
  it('uses <slug>-<env> for Doppler and Supabase projects', async () => {
    const readme = (await generate('product', 'naming-app')).read('README.md')
    for (const env of ['dev', 'test', 'stg', 'prod']) {
      expect(readme).toContain(`\`naming-app-${env}\``)
    }
  })

  it('uses <slug>-<service>-<env> for Fly apps', async () => {
    const readme = (await generate('control-plane', 'naming-cp')).read('README.md')
    expect(readme).toContain('`naming-cp-api-dev`')
    expect(readme).toContain('`naming-cp-scheduler-prod`')
  })

  it('does not suffix the ZITADEL project with the environment', async () => {
    const readme = (await generate('product', 'naming-zitadel')).read('README.md')
    expect(readme).toContain('ZITADEL project name is `naming-zitadel`')
    expect(readme).not.toMatch(/ZITADEL project name is `naming-zitadel-(dev|test|stg|prod)`/)
  })

  it('declares the four immutable environments for both profiles', () => {
    for (const profile of ['product', 'control-plane'] as ProfileName[]) {
      expect(loadProfile(profile).manifest.environments).toEqual(['dev', 'test', 'stg', 'prod'])
    }
  })
})

// ── registration behaviour ───────────────────────────────────────────────────

describe('registration behaviour', () => {
  it('product registers itself as a product', () => {
    const { manifest } = loadProfile('product')
    expect(manifest.registration.registers_as_product).toBe(true)
    expect(manifest.registration.endpoint).toBe('/api/platform/v1/products')
  })

  it('control-plane never registers itself', () => {
    const { manifest } = loadProfile('control-plane')
    expect(manifest.registration.registers_as_product).toBe(false)
    expect(manifest.registration.endpoint).toBeUndefined()
  })

  it('control-plane output contains no registration client or endpoint call', async () => {
    const gen = await generate('control-plane', 'reg-cp')
    expect(gen.has('packages/control-plane-client')).toBe(false)
    expect(gen.read('README.md')).toContain('the Control Plane never registers itself')
  })
})

// ── profile validation ───────────────────────────────────────────────────────

describe('profile validation', () => {
  it('accepts the supported profiles', () => {
    expect(validateProfile('product').valid).toBe(true)
    expect(validateProfile('control-plane').valid).toBe(true)
  })

  it('rejects an unknown profile with an actionable error', () => {
    const result = validateProfile('saas')
    expect(result.valid).toBe(false)
    expect(result.error).toMatch(/Unknown profile "saas"/)
    expect(result.error).toMatch(/product, control-plane/)
  })

  it('requires a profile when none is given', () => {
    expect(validateProfile('').valid).toBe(false)
  })
})

// ── local stack host ports ───────────────────────────────────────────────────

describe('local stack host ports', () => {
  const composeOf = async (profile: ProfileName, slug: string) =>
    (await generate(profile, slug)).read('local/docker-compose.yml')

  const publishedPorts = (compose: string) =>
    [...compose.matchAll(/- "\$\{(KORAS_PORT_[A-Z_]+):-(\d+)\}:(\d+)"/g)].map((m) => ({
      variable: m[1],
      preferred: Number(m[2]),
      container: Number(m[3]),
    }))

  it('publishes every port through a resolvable variable', async () => {
    for (const [profile, slug] of [
      ['product', 'ports-product'],
      ['control-plane', 'ports-cp'],
    ] as Array<[ProfileName, string]>) {
      const compose = await composeOf(profile, slug)
      // A bare "1234:5432" would be a host port no machine can override.
      expect(compose).not.toMatch(/- "\d+:\d+"/)
      expect(publishedPorts(compose).length).toBeGreaterThan(0)
    }
  })

  it('never asks for a privileged host port', async () => {
    // Binding <1024 needs root on Linux, and 80 is reserved by http.sys on
    // Windows whenever IIS is installed.
    for (const [profile, slug] of [
      ['product', 'ports-priv-product'],
      ['control-plane', 'ports-priv-cp'],
    ] as Array<[ProfileName, string]>) {
      for (const p of publishedPorts(await composeOf(profile, slug))) {
        expect(p.preferred).toBeGreaterThanOrEqual(1024)
      }
    }
  })

  it('gives the two profiles disjoint preferences so they can co-run', async () => {
    const product = publishedPorts(await composeOf('product', 'ports-dis-product')).map((p) => p.preferred)
    const cp = publishedPorts(await composeOf('control-plane', 'ports-dis-cp')).map((p) => p.preferred)
    expect(product.filter((p) => cp.includes(p))).toEqual([])
  })

  it('ships a resolver and wires bootstrap to it', async () => {
    for (const [profile, slug] of [
      ['product', 'ports-res-product'],
      ['control-plane', 'ports-res-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      expect(gen.has('local/scripts/ports.sh')).toBe(true)
      const bootstrap = gen.read('local/scripts/bootstrap.sh')
      expect(bootstrap).toContain('local/scripts/ports.sh')
      // Resolution has to happen before anything tries to bind.
      expect(bootstrap.indexOf('ports.sh')).toBeLessThan(bootstrap.indexOf('docker compose'))
    }
  })

  it('healthchecks inside a container use the container port', async () => {
    // The mail healthcheck runs in the container, where the host mapping is
    // invisible; it only ever worked because host and container ports matched.
    for (const [profile, slug] of [
      ['product', 'ports-hc-product'],
      ['control-plane', 'ports-hc-cp'],
    ] as Array<[ProfileName, string]>) {
      expect(await composeOf(profile, slug)).toContain('http://localhost:8025/')
    }
  })
})

// ── host dev-server ports ────────────────────────────────────────────────────

describe('host dev-server ports', () => {
  it('never hardcodes a dev-server port in package.json', async () => {
    // `next dev --port 3000` is a host-global claim that collides with any
    // other project running at the same time.
    for (const [profile, slug, apps] of [
      ['product', 'devport-product', ['web', 'admin', 'marketing']],
      ['control-plane', 'devport-cp', ['admin', 'portal']],
    ] as Array<[ProfileName, string, string[]]>) {
      const gen = await generate(profile, slug)
      // Only the apps this profile's defaults actually enable are emitted.
      const present = apps.filter((app) => gen.has(`apps/${app}/package.json`))
      expect(present.length).toBeGreaterThan(0)
      for (const app of present) {
        const pkg = JSON.parse(gen.read(`apps/${app}/package.json`))
        expect(pkg.scripts.dev).not.toMatch(/--port \d+/)
        expect(pkg.scripts.dev).toContain('dev-app.mjs')
      }
      expect(gen.has('local/scripts/dev-app.mjs')).toBe(true)
    }
  })

  it('resolves every app port through the shared resolver', async () => {
    for (const [profile, slug] of [
      ['product', 'devport-res-product'],
      ['control-plane', 'devport-res-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      const declared = [...gen.read('local/scripts/ports.sh').matchAll(/^(KORAS_PORT_APP_[A-Z]+) /gm)]
        .map((m) => m[1])
      expect(declared.length).toBeGreaterThan(0)
      // Whatever the apps ask for must be something ports.sh actually assigns.
      const requested = [...gen.read('local/scripts/ports.sh').matchAll(/KORAS_PORT_APP_[A-Z]+/g)]
      expect(requested.length).toBeGreaterThan(0)
    }
  })

  it('points Caddy at the resolved ports and hands them to the container', async () => {
    for (const [profile, slug] of [
      ['product', 'devport-caddy-product'],
      ['control-plane', 'devport-caddy-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = await generate(profile, slug)
      const caddy = gen.read('local/proxy/Caddyfile')
      // A literal upstream would proxy to whatever else grabbed that port.
      expect(caddy).not.toMatch(/reverse_proxy host\.docker\.internal:\d+/)
      const compose = gen.read('local/docker-compose.yml')
      for (const [, variable] of caddy.matchAll(/\{env\.(KORAS_PORT_[A-Z_]+)\}/g)) {
        // Caddy expands {env.X} inside the container, so it must be passed in.
        expect(compose).toContain(`${variable}: `)
      }
    }
  })

  describe('shared platform primitives', () => {
    const SHARED = [
      'python-packages/koras-platform/pyproject.toml',
      'python-packages/koras-platform/src/koras_platform/__init__.py',
      'python-packages/koras-platform/src/koras_platform/environment.py',
      'python-packages/koras-platform/src/koras_platform/adapters.py',
      'python-packages/koras-platform/src/koras_platform/roles.py',
    ]

    it('ships koras-platform to both profiles', async () => {
      for (const profile of ['product', 'control-plane'] as ProfileName[]) {
        const gen = await generate(profile, `platform-pkg-${profile}`)
        for (const file of SHARED) {
          expect(gen.has(file), `${profile} is missing ${file}`).toBe(true)
        }
      }
    })

    it('ships byte-identical copies to both profiles', async () => {
      // The starter has no common template layer, so shared packages are
      // duplicated per profile. Nothing else stops the two drifting apart.
      const product = await generate('product', 'platform-same-product')
      const cp = await generate('control-plane', 'platform-same-cp')
      for (const file of SHARED) {
        expect(cp.read(file), `${file} differs between profiles`).toBe(product.read(file))
      }
    })

    it('defines all four environments and no default', async () => {
      const source = (await generate('product', 'platform-env')).read(
        'python-packages/koras-platform/src/koras_platform/environment.py',
      )
      for (const env of ['dev', 'test', 'stg', 'prod']) {
        expect(source).toContain(`"${env}"`)
      }
      // A default would make a missing ENVIRONMENT resolve silently, and the
      // isolation guarantee rests entirely on this value being correct.
      expect(source).toMatch(/def resolve_environment\(value: str \| Environment \| None\)/)
      expect(source).toContain('raise ValueError')
    })

    it('keeps platform roles out of product repositories', async () => {
      // KORAS staff roles are Control Plane authority. A product that could
      // reference them is a product that could accidentally honour them.
      const roles = (await generate('product', 'platform-roles')).read(
        'python-packages/koras-platform/src/koras_platform/roles.py',
      )
      expect(roles).toContain('organization_owner')
      expect(roles).not.toContain('platform_super_admin')
      expect(roles).not.toContain('platform_billing')
    })

    it('makes the adapter environment explicit and self-checking', async () => {
      const source = (await generate('control-plane', 'platform-adapter')).read(
        'python-packages/koras-platform/src/koras_platform/adapters.py',
      )
      // Required argument, not an optional one with a default to inherit.
      expect(source).toContain('process_environment: Environment')
      expect(source).toContain('EnvironmentIsolationError')
      expect(source).not.toMatch(/environment.*=\s*Environment\.(DEV|PROD)/)
    })
  })

  it('keeps the two profiles on separate dev-server blocks', async () => {
    const portsOf = async (profile: ProfileName, slug: string) =>
      [...(await generate(profile, slug)).read('local/scripts/ports.sh')
        .matchAll(/^KORAS_PORT_(?:APP|SERVICE)_[A-Z]+ (\d+)$/gm)].map((m) => Number(m[1]))
    const product = await portsOf('product', 'devport-sep-product')
    const cp = await portsOf('control-plane', 'devport-sep-cp')
    expect(product.length).toBeGreaterThan(0)
    expect(cp.length).toBeGreaterThan(0)
    expect(product.filter((p) => cp.includes(p))).toEqual([])
  })
})

// -- secret-handling scaffold -------------------------------------------------
// A generated project publishes its estate's credentials if a Terraform plan
// ends up committed, and looks correctly configured while Doppler is empty.
// Both are shipped closed rather than left to each project to remember.

describe.each(['product', 'control-plane'] as const)('%s secret scaffold', (profile) => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate(profile, `${profile}-secretscaffold`)
  })

  it('ignores Terraform plan files', () => {
    // A plan embeds a full state snapshot. No content scanner sees inside one:
    // gitleaks decides what is an archive from the file extension, and a plan
    // file has none.
    const ignore = gen.read('.gitignore')
    expect(ignore).toMatch(/^tfplan$/m)
    expect(ignore).toMatch(/^\*\.tfplan$/m)
  })

  it('still permits the Terraform files that belong in the repository', () => {
    const ignore = gen.read('.gitignore')
    expect(ignore).toContain('!infrastructure/terraform/terraform.tfvars')
  })

  it('carries the check that forbids committed state', () => {
    expect(gen.has('tests/security/test_no_state_artifacts.py')).toBe(true)
  })

  it('carries the Doppler completeness check, wired to make', () => {
    expect(gen.has('local/scripts/doppler-check.sh')).toBe(true)
    expect(gen.read('Makefile')).toContain('doppler-check:')
  })

  it('points the Doppler check at this project', () => {
    // Rendered, not left as a template placeholder -- a check that reads the
    // wrong project reports every setting missing and gets ignored.
    const script = gen.read('local/scripts/doppler-check.sh')
    expect(script).toContain(`${profile}-secretscaffold`)
    expect(script).not.toContain('{{')
  })

  it('classifies every setting in the manifest', () => {
    // The manifest decides what a deployed environment needs. A setting present
    // in the local contract and absent here is one nobody classified, and the
    // failure is silent: it simply never gets checked.
    const contract = gen
      .read('local/config/.env.local.example')
      .split('\n')
      .filter((line) => line.trim() && !line.trim().startsWith('#'))
      .map((line) => line.split('=')[0].trim())
    const manifest = gen
      .read('local/config/secrets.manifest')
      .split('\n')
      .filter((line) => line.trim() && !line.trim().startsWith('#'))
      .map((line) => line.split(/\s+/)[0])

    const unclassified = contract.filter((key) => !manifest.includes(key))
    expect(unclassified).toEqual([])
  })

  it('keeps the local Docker stack out of Doppler', () => {
    // MinIO, Grafana and LiteLLM run locally and nowhere else. An earlier
    // version classified from a hardcoded list and would have demanded a MinIO
    // root password in production Doppler for a product project.
    const manifest = gen.read('local/config/secrets.manifest')
    const classOf = (key: string) =>
      manifest
        .split('\n')
        .find((line) => line.startsWith(`${key} `))
        ?.split(/\s+/)[1]

    expect(classOf('NODE_ENV')).toBe('local')
    // Mail is the one thing a product sends itself since 2026-09-14 -- the
    // assistant's approval notice -- so its SMTP settings are optional and
    // deployable there, the move the Control Plane made for its own mail.
    // The Control Plane profile's template still keeps them local.
    expect(classOf('SMTP_HOST')).toBe(profile === 'product' ? 'optional' : 'local')
    if (profile === 'product') {
      for (const key of ['MINIO_ROOT_PASSWORD', 'GRAFANA_PASSWORD', 'ZITADEL_MASTERKEY']) {
        expect(classOf(key)).toBe('local')
      }
    }
  })

  it('gives every derived setting a source', () => {
    // Without one the lookup falls back to a prompt and the derivation quietly
    // does nothing -- which is exactly what happened when the source column did
    // not exist.
    const rows = gen
      .read('local/config/secrets.manifest')
      .split('\n')
      .filter((line) => line.trim() && !line.trim().startsWith('#'))
      .map((line) => line.split(/\s+/))

    for (const [name, klass, source] of rows) {
      if (klass !== 'derived') continue
      expect(source, `${name} is derived with no source`).toMatch(/^(out:|const:|self:)/)
    }
  })

  it('carries the bootstrap and its helper', () => {
    expect(gen.has('local/scripts/doppler-bootstrap.sh')).toBe(true)
    expect(gen.has('local/scripts/doppler_bootstrap_support.py')).toBe(true)
    expect(gen.read('Makefile')).toContain('doppler-bootstrap:')
  })

  it('never puts a secret on a command line', () => {
    // `doppler secrets set NAME value` would place the value in ps output for
    // every user on the machine and in shell history forever. stdin is the
    // documented path and the only acceptable one here.
    const script = gen.read('local/scripts/doppler-bootstrap.sh')
    expect(script).toContain('read -rs')
    expect(script).toMatch(/doppler secrets set "\$name"[\s\S]{0,120}--no-interactive/)
    expect(script).not.toMatch(/doppler secrets set \S+ "\$value"/)
  })

  it('leaves production alone unless asked for by name', () => {
    const script = gen.read('local/scripts/doppler-bootstrap.sh')
    expect(script).toMatch(/ENVIRONMENTS=\(dev test stg\)/)
  })

  it('never asks Doppler for a value', () => {
    // The check runs in CI. It lists names so that it cannot leak what it does
    // not fetch.
    const script = gen.read('local/scripts/doppler-check.sh')
    expect(script).toContain('--only-names')
  })
})

// ── recorded selections ──────────────────────────────────────────────────────

describe('the project manifest records its components', () => {
  it('lists the enabled applications, services and capabilities', async () => {
    const gen = await generate('control-plane', 'manifest-cp')
    const manifest = parseProjectManifest(gen.read('.koras/project.yaml'), 'test')

    expect(manifest.components).toBeDefined()
    expect(manifest.components!.applications).toEqual(['platform_admin', 'portal'])
    expect(manifest.components!.services).toEqual(['api', 'scheduler', 'worker'])
  })

  it('records only what is enabled', async () => {
    // marketing is off by default for the product profile.
    const gen = await generate('product', 'manifest-product')
    const manifest = parseProjectManifest(gen.read('.koras/project.yaml'), 'test')

    expect(manifest.components!.applications).not.toContain('marketing')
    expect(manifest.components!.applications).toEqual(['admin', 'web'])
  })

  it('still parses a manifest written before the field existed', async () => {
    // Backward compatible on purpose: schema_version does not move for an
    // added optional field, so existing projects keep validating.
    const gen = await generate('product', 'manifest-old')
    const withoutComponents = gen.read('.koras/project.yaml').replace(/components:[\s\S]*$/, '')

    const manifest = parseProjectManifest(withoutComponents, 'test')
    expect(manifest.components).toBeUndefined()
    expect(manifest.project.profile).toBe('product')
  })
})

// ── application security headers ─────────────────────────────────────────────

describe('every generated app ships security headers', () => {
  it('gives each application a next.config, not just one of them', async () => {
    for (const [profile, slug, apps] of [
      ['product', 'hdr-product', ['web', 'admin']],
      ['control-plane', 'hdr-cp', ['admin', 'portal']],
    ] as Array<[ProfileName, string, string[]]>) {
      const gen = await generate(profile, slug)
      for (const app of apps.filter((a) => gen.has(`apps/${a}/package.json`))) {
        expect(gen.has(`apps/${app}/next.config.ts`)).toBe(true)
      }
    }
  })

  it('sets the headers that do not vary per request', async () => {
    const config = (await generate('control-plane', 'hdr-values')).read('apps/portal/next.config.ts')

    for (const header of [
      'X-Content-Type-Options',
      'X-Frame-Options',
      'Referrer-Policy',
      'Permissions-Policy',
      'Cross-Origin-Opener-Policy',
    ]) {
      expect(config).toContain(header)
    }
    // The header advertises framework and version to anyone scanning.
    expect(config).toContain('poweredByHeader: false')
  })

  it('leaves the CSP to middleware', async () => {
    // Next injects an inline bootstrap script, so a static CSP would need
    // `unsafe-inline`; a nonce has to differ per request.
    const config = (await generate('product', 'hdr-csp')).read('apps/web/next.config.ts')
    // The comment names the header it deliberately omits, so match the entry.
    expect(config).not.toMatch(/key:\s*'Content-Security-Policy'/)
  })

  it('transpiles the workspace packages the app actually depends on', async () => {
    const gen = await generate('product', 'hdr-transpile')
    const pkg = JSON.parse(gen.read('apps/web/package.json'))
    const config = gen.read('apps/web/next.config.ts')

    const workspaceDeps = Object.keys(pkg.dependencies ?? {}).filter(
      (d) => d.startsWith('@hdr-transpile/') && d !== pkg.name,
    )
    expect(workspaceDeps.length).toBeGreaterThan(0)
    for (const dep of workspaceDeps) expect(config).toContain(dep)
  })
})

// -- deployment scaffold ------------------------------------------------------
// A generated project used to ship four workflows that ran `turbo run build`
// and stopped: a green check on every push that meant "the code compiles" while
// claiming to mean "the code is live".

describe.each(['product', 'control-plane'] as const)('%s deployment', (profile) => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate(profile, `${profile}-deployscaffold`)
  })

  it('deploys rather than merely building', () => {
    const deploy = gen.read('.github/workflows/deploy.yml')
    expect(deploy).toContain('flyctl deploy')
    expect(deploy).toMatch(/vercel@\$\{VERCEL_CLI\}" deploy/)
    expect(deploy).toContain('migrate.sh')
  })

  it('loads settings into the app before deploying it', () => {
    // Without this the container starts, fails settings validation on a
    // missing ENVIRONMENT, and crash-loops while the deployment reports
    // success. Doppler holds the values and nothing else carries them across.
    const deploy = gen.read('.github/workflows/deploy.yml')
    expect(deploy).toContain('flyctl secrets import')
    expect(deploy).toContain('doppler secrets download')

    const importAt = deploy.indexOf('flyctl secrets import')
    const deployAt = deploy.indexOf('flyctl deploy')
    expect(importAt).toBeLessThan(deployAt)
  })

  it('never writes downloaded settings to disk', () => {
    // A shared runner keeps the workspace around for anything that reads it.
    const deploy = gen.read('.github/workflows/deploy.yml')
    expect(deploy).toContain('--no-file')
  })

  it('checks its own work', () => {
    const deploy = gen.read('.github/workflows/deploy.yml')
    expect(deploy).toContain('/api/v1/health')
    // The worst deployment failure puts the right code in the wrong estate,
    // and answers every other probe correctly.
    expect(deploy).toMatch(/environment.*inputs\.environment/)
  })

  it('names the app from the repository rather than a template expression', () => {
    // deploy.yml is copied verbatim, never rendered. It is dense with GitHub
    // ${{ ... }} expressions and Handlebars would parse every one of them --
    // turning ${{ secrets.FLY_API_TOKEN }} into an empty string and leaving a
    // workflow that looks correct and authenticates as nobody.
    const deploy = gen.read('.github/workflows/deploy.yml')
    expect(deploy).toContain('github.event.repository.name')
    expect(deploy).not.toContain('{{projectSlug}}')
    expect(deploy).toContain('secrets.FLY_API_TOKEN')
  })
})

describe.each(['product', 'control-plane'] as const)('%s identity roles', (profile) => {
  it('defines the roles the code parses', () => {
    // project_role_assertion puts a caller's roles in the token claim, but a
    // project with none defined can grant none: sign-in succeeds, the session
    // is valid, and every page is refused. A platform nobody can log into.
    const module = readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', 'zitadel', 'main.tf'),
      'utf8',
    )
    expect(module).toContain('zitadel_project_role')

    const expected =
      profile === 'control-plane'
        ? ['platform_super_admin', 'platform_admin', 'platform_support', 'platform_billing', 'platform_readonly']
        : ['organization_owner', 'organization_admin', 'billing_admin', 'security_admin', 'member']
    for (const role of expected) {
      expect(module).toContain(`"${role}"`)
    }
  })
})

// -- hostnames ----------------------------------------------------------------
// Creating a Vercel project was never enough. Without a domain the app answers
// only on its generated *.vercel.app name, so the OAuth redirect URI pointed at
// a hostname that resolved to nothing: sign-in completed and landed on NXDOMAIN.

describe('a generated project is named after itself', () => {
  // Identity from the project this template was extracted from leaks in ways
  // that surface only in production. Two found so far: the session issuer, so
  // every estate signed cookies as though it were that one, and
  // OTEL_SERVICE_NAME, so every generated project reported its traces under the
  // same service and collided in one dashboard. Both were single hardcoded
  // strings that read as harmless.
  //
  // The name used as a *value* is the defect. Prose that mentions the Control
  // Plane is not: a product genuinely talks to it, and its API contract says so
  // in a docstring.
  const SOURCE = ['koras', 'control', 'plane'].join('-')
  const asValue = new RegExp(`(=|:\\s*|["'\`])${SOURCE}(["'\`]|$|\\s)`, 'm')

  for (const profile of ['control-plane', 'product'] as const) {
    it(`${profile}: no generated file carries the source name as a value`, async () => {
      const gen = await generate(profile, `named-${profile}`)
      const offenders: string[] = []
      for (const file of gen.fileList) {
        if (/node_modules|\.lock|pnpm-lock|\.(md|mdx)$/.test(file)) continue
        let text: string
        try {
          text = gen.read(file)
        } catch {
          continue
        }
        if (asValue.test(text)) offenders.push(file)
      }
      expect(offenders).toEqual([])
    })
  }
})

describe('a generated control plane can actually sign someone in', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  beforeAll(async () => {
    gen = await generate('control-plane', 'auth-cp')
  })

  it('ships the routes a sign-in needs', () => {
    // The auth package was a 33-line stub whose verifySession returned null
    // unconditionally, and there were no route handlers at all -- so every
    // generated project redirected every request to /login forever, before
    // anyone configured anything.
    for (const app of ['admin', 'portal']) {
      for (const route of ['start', 'callback', 'signout']) {
        expect(gen.has(`apps/${app}/src/app/api/auth/${route}/route.ts`)).toBe(true)
      }
      expect(gen.has(`apps/${app}/src/middleware.ts`)).toBe(true)
    }
  })

  it('does not verify a session by returning null', () => {
    const auth = gen.read('packages/auth/src/index.ts')
    expect(auth).not.toContain('Verification delegated')
    expect(auth).toContain('export async function readSession')
    expect(auth).toContain('export async function mintSession')
  })

  it('does not carry the destination in the state parameter', () => {
    // One parameter, two defects: a predictable CSRF token, and an open
    // redirect that puts a phishing link on a KORAS domain.
    const oauth = gen.read('packages/auth/src/oauth.ts')
    expect(oauth).toContain('safeReturnPath')
    expect(oauth).toContain('code_challenge_method')
    const auth = gen.read('packages/auth/src/index.ts')
    expect(auth).not.toContain('state: callbackUrl')
  })

  it('reads the session without a network call', () => {
    // The edge runtime could not reach the identity provider the Node runtime
    // could, so verifying the provider's token per request meant every valid
    // session read as no session.
    const auth = gen.read('packages/auth/src/index.ts')
    const reader = auth.slice(auth.indexOf('export async function readSession'))
    expect(reader.slice(0, reader.indexOf('\n}\n'))).not.toContain('jwksFor')
    for (const app of ['admin', 'portal']) {
      expect(gen.read(`apps/${app}/src/middleware.ts`)).toContain('readSession')
    }
  })

  it('names itself, not the project it was extracted from', () => {
    // The session issuer was a hardcoded `koras-control-plane`, so every
    // generated estate signed cookies as though it were that one.
    expect(gen.read('packages/auth/src/index.ts')).toContain("SESSION_ISSUER = 'auth-cp'")
    for (const file of ['packages/auth/src/index.ts', 'packages/auth/src/oauth.ts']) {
      expect(gen.read(file)).not.toContain('koras-control-plane')
    }
  })

  it('asks for the key that signs its cookies', () => {
    expect(gen.read('local/config/secrets.manifest')).toContain('SESSION_SECRET supplied')
    expect(gen.read('local/config/.env.local.example')).toContain('SESSION_SECRET=')
  })

  it('puts the roles in the token the applications read', () => {
    // project_role_assertion governs the access token; the applications read
    // the ID token. Without this a user with a role signs in carrying none,
    // and the middleware answers "this application is for KORAS staff" --
    // the correct refusal for that token, and entirely misleading about why.
    const zitadel = readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform',
           'modules', 'zitadel', 'main.tf'),
      'utf8',
    )
    expect(zitadel).toMatch(/id_token_role_assertion\s*=\s*true/)
    expect(zitadel).toMatch(/id_token_userinfo_assertion\s*=\s*true/)
  })
})

describe('sign-in is configured per environment', () => {
  const bootstrap = () =>
    readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform',
           'modules', 'project-bootstrap', 'main.tf'),
      'utf8',
    )

  it('gives no ZITADEL instance a shared redirect list', () => {
    // `zitadel_redirect_uris` was one flat list passed to all four instances,
    // so dev's ZITADEL would accept prod's callback: an authorization code
    // issued by dev could be redirected into the production application.
    // Every other external adapter takes an explicit environment.
    const main = bootstrap()
    expect(main).not.toContain('redirect_uris             = var.zitadel_redirect_uris')
    for (const environment of ['dev', 'test', 'stg', 'prod']) {
      expect(main).toContain(`local.redirect_uris["${environment}"]`)
      expect(main).toContain(`local.post_logout_redirect_uris["${environment}"]`)
    }
  })

  it('derives the callback URLs from the hostnames Vercel attaches', () => {
    // The list defaulted to empty and nothing set it, so every OIDC app in
    // every generated estate had no redirect URI and ZITADEL refused every
    // sign-in outright. Deriving them means the two cannot disagree.
    const main = bootstrap()
    expect(main).toContain('module.vercel.domains')
    expect(main).toContain('/api/auth/callback')
    expect(main).toContain('endswith(key, "-${environment}")')
  })

  it('keys environments once, for both Vercel and ZITADEL', () => {
    // Two lists of environments is one list that goes stale.
    const main = bootstrap()
    expect(main).toContain('keys(var.environment_branches)')
    expect(main).toContain('environment_branches = var.environment_branches')
  })
})

describe('the deployment pipeline matches the components generated', () => {
  // Every one of these was a real failure, and all three shared a shape: the
  // pipeline named components instead of looking at them, so it stayed green
  // right up to the deploy and then failed on something the repository could
  // have answered.
  const cases: Array<[ProfileName, string, string[], string[]]> = [
    ['product', 'pipe-product', ['api', 'worker'], ['admin', 'web']],
    ['control-plane', 'pipe-cp', ['api', 'scheduler', 'worker'], ['admin', 'portal']],
  ]

  for (const [profile, slug, services, apps] of cases) {
    describe(profile, () => {
      let gen: Awaited<ReturnType<typeof generate>>
      beforeAll(async () => {
        gen = await generate(profile, slug)
      })

      it('names no component in the workflow', () => {
        // The matrices were literal lists copied from the control-plane
        // profile: services [api, worker, scheduler] and applications
        // [admin, portal]. A product has `web`, not `portal`, and two
        // services -- so its pipeline deployed an application that does not
        // exist, never deployed the one that does, and tried to deploy a
        // service with no Dockerfile.
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).not.toContain('service: [api, worker, scheduler]')
        expect(workflow).not.toContain('app: portal')
        expect(workflow).not.toContain('app: admin')
        expect(workflow).toContain('fromJSON(needs.discover.outputs.services)')
        expect(workflow).toContain('fromJSON(needs.discover.outputs.applications)')
      })

      it('pins no action that runs on a deprecated Node', () => {
        // Every workflow run carried ten deprecation warnings. Harmless until
        // GitHub removes the runtime, at which point every pipeline in every
        // generated project fails at once, for a reason none of them changed.
        const stale = ['actions/checkout@v4', 'actions/setup-node@v4', 'astral-sh/setup-uv@v3']
        for (const file of ['deploy.yml', 'ci.yml']) {
          const workflow = gen.read(`.github/workflows/${file}`)
          for (const action of stale) {
            expect(workflow).not.toContain(action)
          }
        }
      })

      it('proves the identity provider answers before deploying', () => {
        // Names were checked and values never were, and the value that broke
        // sign-in was present and the wrong shape: a bare hostname where a base
        // URL was meant. Every job stayed green through four environments while
        // no one could sign in to any of them.
        //
        // Fetching the key set proves the chain in one public request -- the
        // value parses, the host resolves, TLS works, and the provider is the
        // one this release will verify tokens against.
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).toContain('oauth/v2/keys')
        expect(workflow).toContain('ZITADEL_DOMAIN is not a base URL')
        // Before the migration, not after the deployment.
        const settings = workflow.indexOf('oauth/v2/keys')
        const migrate = workflow.indexOf('  migrate:')
        expect(settings).toBeGreaterThan(-1)
        expect(settings).toBeLessThan(migrate)
      })

      it('pins the Vercel CLI', () => {
        // It was vercel@latest, so a CLI release broke every deployment in
        // every environment on a day nothing in this repository changed:
        // 59.4.0 began defaulting new variables to sensitive. A deployment
        // pipeline should fail because of what was committed.
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).not.toContain('vercel@latest')
        expect(workflow).toMatch(/VERCEL_CLI: '\d+\.\d+\.\d+'/)
      })

      it('does not label a public variable as a secret', () => {
        // NEXT_PUBLIC_ values are compiled into the browser bundle, so storing
        // them as secrets is a claim the deployment contradicts the moment it
        // ships. Vercel refuses the combination, which is how this surfaced.
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).toContain('NEXT_PUBLIC_*)')
        expect(workflow).toContain('--no-sensitive --visibility config')
        // And only for those: everything else must stay sensitive.
        expect(workflow).toContain('$scope $visibility')
      })

      it('every job names an environment', () => {
        // Not cosmetic. This workflow declares its secrets `required: true`,
        // the callers pass `secrets: inherit`, and inherit carries only
        // repository-level secrets -- these live on the GitHub environment.
        // A job that names no environment cannot satisfy the declaration, so
        // the whole run is rejected before a single step executes, citing
        // secrets that job never reads. The discover job shipped without one
        // and took the entire pipeline down with it.
        // Scanned rather than parsed: the generator has no YAML dependency,
        // and adding one to assert two-space indentation would be its own
        // kind of overreach.
        const lines = gen.read('.github/workflows/deploy.yml').replace(/\r/g, '').split('\n')
        const start = lines.findIndex((l) => l === 'jobs:')
        expect(start).toBeGreaterThan(-1)

        const missing: string[] = []
        let current: string | null = null
        let hasEnvironment = false
        for (const line of lines.slice(start + 1)) {
          const header = /^ {2}([A-Za-z0-9_-]+):\s*$/.exec(line)
          if (header) {
            if (current && !hasEnvironment) missing.push(current)
            current = header[1]
            hasEnvironment = false
            continue
          }
          if (current && /^ {4}environment:/.test(line)) hasEnvironment = true
        }
        if (current && !hasEnvironment) missing.push(current)

        expect(missing).toEqual([])
      })

      it('refuses to report success having deployed nothing', () => {
        // The guard that would have caught all of this: an empty matrix is a
        // green pipeline that shipped no code, which is indistinguishable
        // from a working one until someone checks the running version.
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).toContain('No deployable components found')
      })

      it('every service it will try to deploy can be deployed', () => {
        // flyctl is invoked with --config services/<svc>/fly.toml and
        // --dockerfile services/<svc>/Dockerfile. The generator wrote the
        // Dockerfile and never the fly.toml, so no generated project could
        // deploy a service at all -- this repository has them only because
        // they were written by hand.
        for (const service of services) {
          expect(gen.has(`services/${service}/Dockerfile`)).toBe(true)
          expect(gen.has(`services/${service}/fly.toml`)).toBe(true)
        }
      })

      it('discovery finds exactly the components on disk', () => {
        // Mirrors the shell in the discover job: a service is a directory
        // holding both files, an application is one holding a package.json.
        const found = services.filter(
          (svc) => gen.has(`services/${svc}/Dockerfile`) && gen.has(`services/${svc}/fly.toml`),
        )
        expect(found).toEqual(services)
        for (const app of apps) {
          expect(gen.has(`apps/${app}/package.json`)).toBe(true)
        }
      })

      it('derives each project id secret from the application directory', () => {
        const workflow = gen.read('.github/workflows/deploy.yml')
        expect(workflow).toContain('ascii_upcase')
        expect(workflow).toContain('_PROJECT_ID')
        // Named nowhere, so it cannot name the wrong one.
        expect(workflow).not.toContain('VERCEL_PORTAL_PROJECT_ID')
      })
    })
  }
})

describe('application hostnames', () => {
  const moduleFile = (name: string) =>
    readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', name, 'main.tf'),
      'utf8',
    )

  it('attaches a domain to every Vercel project', () => {
    expect(moduleFile('vercel')).toContain('vercel_project_domain')
  })

  it('gives every environment its own project', () => {
    // Two projects and four environments does not work: a Vercel project has
    // three env-var targets, not one per estate, so isolating four needs
    // branch-scoped preview variables -- and Vercel only learns branches from
    // git-triggered deploys, which CLI deploys never are.
    const vercel = moduleFile('vercel')

    // Asserted on what the resource iterates, not on the file merely mentioning
    // the matrix. The first version of this checked for the string and passed
    // happily when for_each was reverted to one project per app.
    const project = vercel.slice(vercel.indexOf('resource "vercel_project" "apps"'))
    expect(project.slice(0, project.indexOf('}'))).toContain('for_each = local.project_matrix')

    expect(vercel).toContain('each.value.environment')
    expect(vercel).toContain('production_branch = each.value.branch')
  })

  it('needs no branch binding on a domain', () => {
    // The project is the environment, so its production deployment is the only
    // thing the hostname should point at. The branch-bound variant could not be
    // created at all until the project had already deployed once.
    const vercel = moduleFile('vercel')
    expect(vercel).toContain('vercel_project_domain" "primary"')
    expect(vercel).not.toContain('git_branch')
  })

  it('never lets Vercel deploy from the connected repository', () => {
    // deploy.yml builds on the runner and ships with `deploy --prebuilt`, so
    // CI's deployments cost no Vercel build minutes. A connected repository
    // builds every push on every project unless told not to, and those builds
    // are the billed ones: 16,108 CPU minutes in one month (R-043).
    //
    // The switch is not a project attribute. `create_deployments = false` was
    // applied first and the next push still built on all fourteen projects;
    // it toggles GitHub deployment_status events. What Vercel documents is
    // `git.deploymentEnabled: false` in a vercel.json at the root directory,
    // so every template app directory must ship one.
    const templateRoot = join(__dirname, '..', '..', '..', 'profiles')
    const appDirs = readdirSync(templateRoot)
      .flatMap((profile) => {
        const apps = join(templateRoot, profile, 'template', 'apps')
        return existsSync(apps) ? readdirSync(apps).map((app) => join(apps, app)) : []
      })
      .filter((dir) => statSync(dir).isDirectory())
    expect(appDirs.length).toBeGreaterThan(0)
    for (const dir of appDirs) {
      // The shared layer is walked first, so an app that both profiles carry
      // (apps/admin) ships the file once, from _shared, not once per profile.
      const shared = join(templateRoot, '_shared', 'template', 'apps', basename(dir), 'vercel.json')
      const file = existsSync(join(dir, 'vercel.json')) ? join(dir, 'vercel.json') : shared
      const config = JSON.parse(readFileSync(file, 'utf8'))
      expect(config.git?.deploymentEnabled, dir).toBe(false)
    }

    // And the module must not claim otherwise.
    expect(moduleFile('vercel')).not.toMatch(/create_deployments\s*=/)

    // The provider pin moved to 5.x with the same change; an estate whose lock
    // holds 5.x cannot init against a 2.x pin, and Terraform intersects the
    // root pin with both module pins.
    const providers = readFileSync(
      join(__dirname, '..', '..', '..', 'profiles', '_shared', 'template', 'infrastructure', 'terraform', 'providers.tf.hbs'),
      'utf8',
    )
    const vercelPin = providers.slice(providers.indexOf('vercel/vercel'))
    expect(vercelPin.slice(0, vercelPin.indexOf('}'))).toContain('version = "~> 5.0"')
    for (const name of ['vercel', 'project-bootstrap']) {
      const modulePins = readFileSync(
        join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', name, 'providers.tf'),
        'utf8',
      )
      const pin = modulePins.slice(modulePins.indexOf('vercel/vercel'))
      expect(pin.slice(0, pin.indexOf('}'))).toContain('version = "~> 5.0"')
    }
  })

  it('ships no Terraform working files with the shared modules', () => {
    // The engine skipped a directory named `.terraform` and said so in a
    // comment, which did nothing about `.terraform.lock.hcl` sitting beside it:
    // the name only starts the same way. Two of those were committed to the
    // starter after an init inside a module directory, and --refresh-modules
    // copied them into a real project as though they were part of the module.
    //
    // A lock belongs to a root configuration. The modules are not root
    // configurations, so one here is meaningless at best and pins a generated
    // project to whatever versions someone happened to have at worst.
    const modules = join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules')
    const strays: string[] = []
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === '.terraform' || entry.name === '.terraform.lock.hcl') {
          strays.push(join(dir, entry.name))
          continue
        }
        if (entry.isDirectory()) walk(join(dir, entry.name))
      }
    }
    walk(modules)
    expect(strays).toEqual([])
  })

  it('does not describe a preview scoping it no longer does', () => {
    // A comment that contradicts the code is worse than no comment. The old one
    // said every non-production environment was "a preview pinned to its own
    // branch" and survived the rewrite sitting directly above target=production
    // -- so the file simultaneously claimed both models. Someone debugging a
    // settings problem would read the comment, believe previews were involved,
    // and go looking for a branch scope that is not there.
    for (const profile of ['control-plane', 'product']) {
      const workflow = readFileSync(
        templatePath(profile, '.github', 'workflows', 'deploy.yml'),
        'utf8',
      )
      expect(workflow).not.toMatch(/pinned to its own branch/)
      expect(workflow).toContain('target="production"')
      expect(workflow).toContain('scope=""')
      // Every environment deploys to its own project's production.
      expect(workflow).not.toMatch(/--target[= ]preview/)
    }
  })

  it('builds the package that actually exists', () => {
    // The default was the literal string
    // "pnpm turbo run build --filter=@PROJECT_SLUG/APP_NAME". Nothing
    // substituted it, so every project carried a build command naming a
    // package that cannot exist -- and it failed only at the first real
    // deployment, with "No package found".
    const vercel = moduleFile('vercel')
    expect(vercel).not.toContain('@PROJECT_SLUG/APP_NAME')
    expect(vercel).toContain('local.package_names[each.value.app]')

    const variables = readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', 'vercel', 'variables.tf'),
      'utf8',
    )
    const block = variables.slice(variables.indexOf('variable "build_command"'))
    expect(block.slice(0, block.indexOf('variable', 10))).toMatch(/default\s*=\s*null/)
  })

  it('names the package after the directory, not the component key', () => {
    // platform_admin lives in apps/admin and is published as @slug/admin.
    // Deriving from the key would name a package nothing publishes.
    expect(moduleFile('vercel')).toContain('basename(lookup(var.application_source_dirs')
  })

  it('creates DNS for every attached domain', () => {
    // A hostname with no record is unreachable; a record with no hostname points
    // at Vercel for a domain it will not serve.
    const outputs = readFileSync(
      join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules', 'vercel', 'outputs.tf'),
      'utf8',
    )
    expect(outputs).toContain('vercel_project_domain.primary')
    expect(moduleFile('project-bootstrap')).toContain('module.vercel.domains')
  })

  it('creates a DNS record for each attached domain', () => {
    const bootstrap = moduleFile('project-bootstrap')
    expect(bootstrap).toContain('module.vercel.domains')
    expect(bootstrap).toContain('cname.vercel-dns.com')
    expect(bootstrap).not.toMatch(/dns_records\s*=\s*\[\]/)
  })

  it('does not proxy the Vercel hostnames through Cloudflare', () => {
    // Vercel terminates TLS for the domain itself. Proxying puts a second
    // certificate in front of a valid one, which fails until Vercel has issued
    // and then serves the wrong chain.
    expect(moduleFile('project-bootstrap')).toMatch(/proxied\s*=\s*false/)
  })
})

