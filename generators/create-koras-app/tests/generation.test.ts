import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'
import { validateProfile } from '../src/validation/profile.js'

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

function generate(profile: ProfileName, slug: string, overrides: Overrides = {}) {
  const ctx = makeCtx(profile, slug, overrides)
  const { fileList } = writeFiles(ctx, renderTemplate(ctx))
  return {
    fileList,
    has: (prefix: string) => fileList.some((f) => f === prefix || f.startsWith(`${prefix}/`)),
    read: (relPath: string) => readFileSync(join(OUT, slug, relPath), 'utf8'),
  }
}

// ── dry run ──────────────────────────────────────────────────────────────────

describe('dry run', () => {
  it('lists files without writing any', () => {
    const ctx = makeCtx('product', 'dry-run-app', {}, true)
    const result = writeFiles(ctx, renderTemplate(ctx))
    expect(result.filesWritten).toBe(0)
    expect(result.fileList.length).toBeGreaterThan(10)
    expect(existsSync(join(OUT, 'dry-run-app'))).toBe(false)
  })
})

// ── product profile ──────────────────────────────────────────────────────────

describe('generate product', () => {
  let gen: ReturnType<typeof generate>

  beforeAll(() => {
    gen = generate('product', 'sampleapp')
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

  it('includes the Control Plane client package', () => {
    expect(gen.has('packages/control-plane-client')).toBe(true)
  })

  it('generates the product registration contract', () => {
    const contract = gen.read('packages/control-plane-client/src/index.ts')
    expect(contract).toContain("REGISTRATION_ENDPOINT = '/api/platform/v1/products'")
    expect(contract).toContain('sampleapp-dev')
    expect(contract).toContain('sampleapp-prod')
  })

  it('renders the slug into package.json', () => {
    expect(gen.read('package.json')).toContain('sampleapp')
  })
})

describe('product optional components', () => {
  it('can enable marketing and the AI Gateway', () => {
    const gen = generate('product', 'sampleapp-full', { with: ['marketing', 'ai_gateway'] })
    expect(gen.has('apps/marketing')).toBe(true)
    expect(gen.has('services/ai-gateway')).toBe(true)
  })

  it('can disable optional components without losing required ones', () => {
    const gen = generate('product', 'sampleapp-min', { without: ['admin', 'worker'] })
    expect(gen.has('apps/admin')).toBe(false)
    expect(gen.has('services/worker')).toBe(false)
    expect(gen.has('apps/web')).toBe(true)
    expect(gen.has('services/api')).toBe(true)
  })

  it('applies the capability matrix to template selection', () => {
    const gen = generate('product', 'sampleapp-nobilling', { without: ['billing'] })
    expect(gen.has('packages/billing')).toBe(false)
    expect(gen.has('packages/domains')).toBe(true) // custom_domains still enabled
  })

  it('rejects an unknown component with an actionable error', () => {
    expect(() => generate('product', 'sampleapp-bad', { with: ['nope'] })).toThrow(
      /Unknown component "nope".*Known components/s,
    )
  })

  it('rejects disabling a required component', () => {
    expect(() => generate('product', 'sampleapp-noapi', { without: ['api'] })).toThrow(
      /Service "api" is required/,
    )
  })
})

// ── control-plane profile ────────────────────────────────────────────────────

describe('generate control-plane', () => {
  let gen: ReturnType<typeof generate>

  beforeAll(() => {
    gen = generate('control-plane', 'koras-control-plane')
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
    expect(gen.has('services/api/src/routers/products.py')).toBe(true)
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
      let gen: ReturnType<typeof generate>
      beforeAll(() => {
        gen = generate(profile, slug)
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

  it('excludes deselected services from Terraform inputs', () => {
    const gen = generate('product', 'prop-tf-min', { without: ['worker'] })
    const tfvars = gen.read('infrastructure/terraform/terraform.tfvars')
    const services = JSON.parse(/enabled_services = (\[.*\])/.exec(tfvars)![1]) as string[]
    expect(services).toContain('api')
    expect(services).not.toContain('worker')
  })
})

// ── shared assets ────────────────────────────────────────────────────────────

describe('shared assets', () => {
  it('bundles the Terraform modules into both profiles', () => {
    for (const [profile, slug] of [
      ['product', 'assets-product'],
      ['control-plane', 'assets-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
      for (const mod of ['project-bootstrap', 'github', 'doppler', 'supabase', 'zitadel']) {
        expect(gen.has(`infrastructure/terraform/modules/${mod}`)).toBe(true)
      }
      // the root module resolves the bundled copy, not a path outside the project
      expect(gen.read('infrastructure/terraform/main.tf')).toContain(
        'source = "./modules/project-bootstrap"',
      )
    }
  })

  it('copies shared assets verbatim, without Handlebars rendering', () => {
    const gen = generate('product', 'assets-verbatim')
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
  it('uses <slug>-<env> for Doppler and Supabase projects', () => {
    const readme = generate('product', 'naming-app').read('README.md')
    for (const env of ['dev', 'test', 'stg', 'prod']) {
      expect(readme).toContain(`\`naming-app-${env}\``)
    }
  })

  it('uses <slug>-<service>-<env> for Fly apps', () => {
    const readme = generate('control-plane', 'naming-cp').read('README.md')
    expect(readme).toContain('`naming-cp-api-dev`')
    expect(readme).toContain('`naming-cp-scheduler-prod`')
  })

  it('does not suffix the ZITADEL project with the environment', () => {
    const readme = generate('product', 'naming-zitadel').read('README.md')
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

  it('control-plane output contains no registration client or endpoint call', () => {
    const gen = generate('control-plane', 'reg-cp')
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
