import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
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

  it('excludes deselected services from Terraform inputs', () => {
    const gen = generate('product', 'prop-tf-min', { without: ['worker'] })
    const tfvars = gen.read('infrastructure/terraform/terraform.tfvars')
    const services = JSON.parse(/enabled_services = (\[.*\])/.exec(tfvars)![1]) as string[]
    expect(services).toContain('api')
    expect(services).not.toContain('worker')
  })
})

// ── line endings ─────────────────────────────────────────────────────────────

describe('line endings', () => {
  it('writes shell scripts, Makefiles, and Dockerfiles with LF', () => {
    // On Windows with core.autocrlf=true the templates themselves carry CRLF,
    // and copying those bytes verbatim gives a project whose `make bootstrap`
    // dies on `set -euo pipefail\r: invalid option name`.
    for (const [profile, slug] of [
      ['product', 'eol-product'],
      ['control-plane', 'eol-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
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

  it('generates a .gitattributes that pins them for later checkouts', () => {
    const gen = generate('product', 'eol-attributes')
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
    let gen: ReturnType<typeof generate>
    beforeAll(() => {
      gen = generate('product', 'docoris')
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
    let gen: ReturnType<typeof generate>
    beforeAll(() => {
      gen = generate('control-plane', 'koras-control-plane')
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
    expect(keyOrder).toEqual(['schema_version', 'project', 'generator'])
    const projectKeys = [...first.matchAll(/^ {2}(\w+):/gm)].map((m) => m[1])
    expect(projectKeys).toEqual(['name', 'slug', 'profile', 'name', 'starter_version', 'profile_version'])
  })

  it('carries no secrets', () => {
    // The header comment says the file holds no secrets; assert on the data.
    const data = generate('product', 'manifest-clean')
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

  it('is reported by --dry-run without being written', () => {
    const ctx = makeCtx('product', 'dry-run-manifest', {}, true)
    const files = renderTemplate(ctx)
    const result = writeFiles(ctx, files)
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

// ── generated project validation ─────────────────────────────────────────────

describe('generated project validation', () => {
  it('accepts a freshly generated project of either profile', () => {
    for (const [profile, slug] of [
      ['product', 'valid-product'],
      ['control-plane', 'valid-cp'],
    ] as Array<[ProfileName, string]>) {
      generate(profile, slug)
      const check = validateGeneratedProject({
        projectRoot: join(OUT, slug),
        expectedSlug: slug,
        expectedProfile: profile,
      })
      expect(check.valid).toBe(true)
      expect(check.manifest!.project.profile).toBe(profile)
    }
  })

  it('fails when the manifest is missing', () => {
    const slug = 'missing-manifest'
    generate('product', slug)
    rmSync(join(OUT, slug, '.koras', 'project.yaml'))
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/has no \.koras\/project\.yaml/)
  })

  it('fails when the manifest is not valid YAML', () => {
    const slug = 'broken-manifest'
    generate('product', slug)
    writeFileSync(join(OUT, slug, '.koras', 'project.yaml'), 'project: [unclosed\n')
    const check = validateGeneratedProject({
      projectRoot: join(OUT, slug),
      expectedSlug: slug,
      expectedProfile: 'product',
    })
    expect(check.valid).toBe(false)
    expect(check.error).toMatch(/not valid YAML/)
  })

  it('fails when the manifest schema version is unsupported', () => {
    const slug = 'future-manifest'
    generate('product', slug)
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

  it('fails when the recorded profile is not the requested one', () => {
    const slug = 'profile-drift'
    generate('control-plane', slug)
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

  it('fails when the recorded slug is not the requested one', () => {
    const slug = 'slug-drift'
    generate('product', slug)
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
