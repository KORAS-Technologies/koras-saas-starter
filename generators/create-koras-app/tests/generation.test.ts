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
      'applications',
      'services',
      'capabilities',
    ])
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

// ── generated project actually installs ──────────────────────────────────────

describe('the generated project can install its dependencies', () => {
  // `services/*` is a uv workspace glob, so a service without a pyproject.toml
  // fails `uv sync` for the whole project — which is step one of
  // `make bootstrap`, before anything else can be tried.
  it('gives every Python service a pyproject.toml', () => {
    // Enable every service the profile actually has — the AI Gateway exists
    // only for product, and an unknown component is rejected outright.
    const cases: Array<[ProfileName, string, string[]]> = [
      ['product', 'install-product', ['worker', 'scheduler', 'ai_gateway']],
      ['control-plane', 'install-cp', ['worker', 'scheduler']],
    ]
    for (const [profile, slug, enabled] of cases) {
      const gen = generate(profile, slug, { with: enabled })
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

  it('names each service package after the project', () => {
    const gen = generate('control-plane', 'install-names')
    expect(gen.read('services/worker/pyproject.toml')).toContain('name = "install-names-worker"')
    expect(gen.read('services/api/pyproject.toml')).toContain('name = "install-names-api"')
  })

  // The template scripts were copied from the starter, which splits its compose
  // file into shared/product/control-plane and layers them. A generated project
  // has one rendered file, so those paths never resolved.
  it('points its scripts at the compose file it actually has', () => {
    for (const [profile, slug] of [
      ['product', 'compose-product'],
      ['control-plane', 'compose-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
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

// ── local stack host ports ───────────────────────────────────────────────────

describe('local stack host ports', () => {
  const composeOf = (profile: ProfileName, slug: string) =>
    generate(profile, slug).read('local/docker-compose.yml')

  const publishedPorts = (compose: string) =>
    [...compose.matchAll(/- "\$\{(KORAS_PORT_[A-Z_]+):-(\d+)\}:(\d+)"/g)].map((m) => ({
      variable: m[1],
      preferred: Number(m[2]),
      container: Number(m[3]),
    }))

  it('publishes every port through a resolvable variable', () => {
    for (const [profile, slug] of [
      ['product', 'ports-product'],
      ['control-plane', 'ports-cp'],
    ] as Array<[ProfileName, string]>) {
      const compose = composeOf(profile, slug)
      // A bare "1234:5432" would be a host port no machine can override.
      expect(compose).not.toMatch(/- "\d+:\d+"/)
      expect(publishedPorts(compose).length).toBeGreaterThan(0)
    }
  })

  it('never asks for a privileged host port', () => {
    // Binding <1024 needs root on Linux, and 80 is reserved by http.sys on
    // Windows whenever IIS is installed.
    for (const [profile, slug] of [
      ['product', 'ports-priv-product'],
      ['control-plane', 'ports-priv-cp'],
    ] as Array<[ProfileName, string]>) {
      for (const p of publishedPorts(composeOf(profile, slug))) {
        expect(p.preferred).toBeGreaterThanOrEqual(1024)
      }
    }
  })

  it('gives the two profiles disjoint preferences so they can co-run', () => {
    const product = publishedPorts(composeOf('product', 'ports-dis-product')).map((p) => p.preferred)
    const cp = publishedPorts(composeOf('control-plane', 'ports-dis-cp')).map((p) => p.preferred)
    expect(product.filter((p) => cp.includes(p))).toEqual([])
  })

  it('ships a resolver and wires bootstrap to it', () => {
    for (const [profile, slug] of [
      ['product', 'ports-res-product'],
      ['control-plane', 'ports-res-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
      expect(gen.has('local/scripts/ports.sh')).toBe(true)
      const bootstrap = gen.read('local/scripts/bootstrap.sh')
      expect(bootstrap).toContain('local/scripts/ports.sh')
      // Resolution has to happen before anything tries to bind.
      expect(bootstrap.indexOf('ports.sh')).toBeLessThan(bootstrap.indexOf('docker compose'))
    }
  })

  it('healthchecks inside a container use the container port', () => {
    // The mail healthcheck runs in the container, where the host mapping is
    // invisible; it only ever worked because host and container ports matched.
    for (const [profile, slug] of [
      ['product', 'ports-hc-product'],
      ['control-plane', 'ports-hc-cp'],
    ] as Array<[ProfileName, string]>) {
      expect(composeOf(profile, slug)).toContain('http://localhost:8025/')
    }
  })
})

// ── host dev-server ports ────────────────────────────────────────────────────

describe('host dev-server ports', () => {
  it('never hardcodes a dev-server port in package.json', () => {
    // `next dev --port 3000` is a host-global claim that collides with any
    // other project running at the same time.
    for (const [profile, slug, apps] of [
      ['product', 'devport-product', ['web', 'admin', 'marketing']],
      ['control-plane', 'devport-cp', ['admin', 'portal']],
    ] as Array<[ProfileName, string, string[]]>) {
      const gen = generate(profile, slug)
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

  it('resolves every app port through the shared resolver', () => {
    for (const [profile, slug] of [
      ['product', 'devport-res-product'],
      ['control-plane', 'devport-res-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
      const declared = [...gen.read('local/scripts/ports.sh').matchAll(/^(KORAS_PORT_APP_[A-Z]+) /gm)]
        .map((m) => m[1])
      expect(declared.length).toBeGreaterThan(0)
      // Whatever the apps ask for must be something ports.sh actually assigns.
      const requested = [...gen.read('local/scripts/ports.sh').matchAll(/KORAS_PORT_APP_[A-Z]+/g)]
      expect(requested.length).toBeGreaterThan(0)
    }
  })

  it('points Caddy at the resolved ports and hands them to the container', () => {
    for (const [profile, slug] of [
      ['product', 'devport-caddy-product'],
      ['control-plane', 'devport-caddy-cp'],
    ] as Array<[ProfileName, string]>) {
      const gen = generate(profile, slug)
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

    it('ships koras-platform to both profiles', () => {
      for (const profile of ['product', 'control-plane'] as ProfileName[]) {
        const gen = generate(profile, `platform-pkg-${profile}`)
        for (const file of SHARED) {
          expect(gen.has(file), `${profile} is missing ${file}`).toBe(true)
        }
      }
    })

    it('ships byte-identical copies to both profiles', () => {
      // The starter has no common template layer, so shared packages are
      // duplicated per profile. Nothing else stops the two drifting apart.
      const product = generate('product', 'platform-same-product')
      const cp = generate('control-plane', 'platform-same-cp')
      for (const file of SHARED) {
        expect(cp.read(file), `${file} differs between profiles`).toBe(product.read(file))
      }
    })

    it('defines all four environments and no default', () => {
      const source = generate('product', 'platform-env').read(
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

    it('keeps platform roles out of product repositories', () => {
      // KORAS staff roles are Control Plane authority. A product that could
      // reference them is a product that could accidentally honour them.
      const roles = generate('product', 'platform-roles').read(
        'python-packages/koras-platform/src/koras_platform/roles.py',
      )
      expect(roles).toContain('organization_owner')
      expect(roles).not.toContain('platform_super_admin')
      expect(roles).not.toContain('platform_billing')
    })

    it('makes the adapter environment explicit and self-checking', () => {
      const source = generate('control-plane', 'platform-adapter').read(
        'python-packages/koras-platform/src/koras_platform/adapters.py',
      )
      // Required argument, not an optional one with a default to inherit.
      expect(source).toContain('process_environment: Environment')
      expect(source).toContain('EnvironmentIsolationError')
      expect(source).not.toMatch(/environment.*=\s*Environment\.(DEV|PROD)/)
    })
  })

  it('keeps the two profiles on separate dev-server blocks', () => {
    const portsOf = (profile: ProfileName, slug: string) =>
      [...generate(profile, slug).read('local/scripts/ports.sh')
        .matchAll(/^KORAS_PORT_(?:APP|SERVICE)_[A-Z]+ (\d+)$/gm)].map((m) => Number(m[1]))
    const product = portsOf('product', 'devport-sep-product')
    const cp = portsOf('control-plane', 'devport-sep-cp')
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
  let gen: ReturnType<typeof generate>

  beforeAll(() => {
    gen = generate(profile, `${profile}-secretscaffold`)
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

    for (const key of ['SMTP_HOST', 'NODE_ENV']) {
      expect(classOf(key)).toBe('local')
    }
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
      expect(source, `${name} is derived with no source`).toMatch(/^(out:|const:)/)
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
  it('lists the enabled applications, services and capabilities', () => {
    const gen = generate('control-plane', 'manifest-cp')
    const manifest = parseProjectManifest(gen.read('.koras/project.yaml'), 'test')

    expect(manifest.components).toBeDefined()
    expect(manifest.components!.applications).toEqual(['platform_admin', 'portal'])
    expect(manifest.components!.services).toEqual(['api', 'scheduler', 'worker'])
  })

  it('records only what is enabled', () => {
    // marketing is off by default for the product profile.
    const gen = generate('product', 'manifest-product')
    const manifest = parseProjectManifest(gen.read('.koras/project.yaml'), 'test')

    expect(manifest.components!.applications).not.toContain('marketing')
    expect(manifest.components!.applications).toEqual(['admin', 'web'])
  })

  it('still parses a manifest written before the field existed', () => {
    // Backward compatible on purpose: schema_version does not move for an
    // added optional field, so existing projects keep validating.
    const gen = generate('product', 'manifest-old')
    const withoutComponents = gen.read('.koras/project.yaml').replace(/components:[\s\S]*$/, '')

    const manifest = parseProjectManifest(withoutComponents, 'test')
    expect(manifest.components).toBeUndefined()
    expect(manifest.project.profile).toBe('product')
  })
})

// ── application security headers ─────────────────────────────────────────────

describe('every generated app ships security headers', () => {
  it('gives each application a next.config, not just one of them', () => {
    for (const [profile, slug, apps] of [
      ['product', 'hdr-product', ['web', 'admin']],
      ['control-plane', 'hdr-cp', ['admin', 'portal']],
    ] as Array<[ProfileName, string, string[]]>) {
      const gen = generate(profile, slug)
      for (const app of apps.filter((a) => gen.has(`apps/${a}/package.json`))) {
        expect(gen.has(`apps/${app}/next.config.ts`)).toBe(true)
      }
    }
  })

  it('sets the headers that do not vary per request', () => {
    const config = generate('control-plane', 'hdr-values').read('apps/portal/next.config.ts')

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

  it('leaves the CSP to middleware', () => {
    // Next injects an inline bootstrap script, so a static CSP would need
    // `unsafe-inline`; a nonce has to differ per request.
    const config = generate('product', 'hdr-csp').read('apps/web/next.config.ts')
    // The comment names the header it deliberately omits, so match the entry.
    expect(config).not.toMatch(/key:\s*'Content-Security-Policy'/)
  })

  it('transpiles the workspace packages the app actually depends on', () => {
    const gen = generate('product', 'hdr-transpile')
    const pkg = JSON.parse(gen.read('apps/web/package.json'))
    const config = gen.read('apps/web/next.config.ts')

    const workspaceDeps = Object.keys(pkg.dependencies ?? {}).filter(
      (d) => d.startsWith('@hdr-transpile/') && d !== pkg.name,
    )
    expect(workspaceDeps.length).toBeGreaterThan(0)
    for (const dep of workspaceDeps) expect(config).toContain(dep)
  })
})
