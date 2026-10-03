import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext, flyAppNames } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'
import { checkDrift } from '../src/generation/drift.js'
import { refreshRenderedPaths } from '../src/generation/refresh.js'
import { parseTerraformOutputs } from '../src/terraform/outputs.js'
import { buildRegistration } from '../src/registration/contract.js'
import { templatePath } from './template-path.js'

/**
 * The clamd service as a generator capability: optional, default off, and
 * invisible to every product that does not ask for it.
 *
 * The first half is the regression that matters most -- a product generated
 * without clamd must be exactly what it was, in every place clamd could have
 * leaked: files, Terraform, the workflow, the README, the recorded components.
 */

const ROOT = join(tmpdir(), `koras-clamd-gen-${process.pid}-${Date.now()}`)
const MODULES = join(__dirname, '..', '..', '..', 'infrastructure', 'terraform', 'modules')

beforeAll(() => mkdirSync(ROOT, { recursive: true }))
afterAll(() => {
  if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true })
})

function ctxFor(profile: ProfileName, slug: string, withs: string[] = []) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, { with: withs })
  validateSelections(manifest, selections)
  return buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: ROOT,
    dryRun: false,
    provision: false,
  })
}

const text = (c: Buffer | string) => (typeof c === 'string' ? c : c.toString('utf8'))

function render(profile: ProfileName, slug: string, withs: string[] = []) {
  const ctx = ctxFor(profile, slug, withs)
  const files = new Map(renderTemplate(ctx).map((f) => [f.outputPath.replace(/\\/g, '/'), text(f.content)]))
  return { ctx, files }
}

const digest = (files: Map<string, string>) =>
  createHash('sha256')
    .update(
      [...files.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([p, c]) => `${p}\0${c}`)
        .join('\0\0'),
    )
    .digest('hex')

describe('a product generated WITHOUT clamd is unchanged', () => {
  const { ctx, files } = render('product', 'plainshop')
  const paths = [...files.keys()]

  it('is off by default', () => {
    expect(ctx.selections.services.clamd).toBe(false)
    expect(loadProfile('product').defaults.services.clamd).toBe(false)
  })

  it('has no clamd service directory', () => {
    expect(paths.filter((p) => p.startsWith('services/clamd'))).toEqual([])
  })

  it('gives NO existing service a descriptor', () => {
    expect(paths.filter((p) => /^services\/[^/]+\/service\.yaml$/.test(p))).toEqual([])
  })

  it('names clamd nowhere in Terraform, the workflows, the README or the recorded project', () => {
    for (const [p, c] of files) {
      if (p.startsWith('.claude/') || p.startsWith('docs/')) continue
      if (/(^|\/)(infrastructure\/terraform\/(?!modules)|\.github\/|README\.md|\.koras\/)/.test(p)) {
        expect(c.toLowerCase(), p).not.toContain('clamd')
      }
    }
  })

  it('creates no clamd Fly app, in any environment', () => {
    expect(flyAppNames(ctx).filter((n) => n.includes('clamd'))).toEqual([])
    expect(files.get('infrastructure/terraform/terraform.tfvars')).toMatch(/enabled_services = \["api", "worker"\]/)
  })

  it('keeps every service it had, untouched by the new mechanism', () => {
    for (const svc of ['api', 'worker']) {
      expect(paths.some((p) => p.startsWith(`services/${svc}/Dockerfile`))).toBe(true)
      expect(files.get(`services/${svc}/fly.toml`)).toBeDefined()
    }
  })

  it('still discovers every service in every environment (legacy semantics)', () => {
    // The workflow's discovery reads descriptors; this product has none, so
    // `api` and `worker` must be eligible everywhere, exactly as before.
    const servicesWithDescriptor = paths.filter((p) => p.endsWith('service.yaml'))
    expect(servicesWithDescriptor).toEqual([])
  })
})

describe('a product generated WITH clamd', () => {
  const { ctx, files } = render('product', 'scanshop', ['clamd'])
  const paths = [...files.keys()]

  it('gets the scanner service, and only that service gains a descriptor', () => {
    expect(paths.filter((p) => p.startsWith('services/clamd/')).sort()).toEqual([
      'services/clamd/Dockerfile',
      'services/clamd/clamd.conf',
      'services/clamd/entrypoint.sh',
      'services/clamd/fly.toml',
      'services/clamd/freshclam.conf',
      'services/clamd/service.yaml',
    ])
    expect(paths.filter((p) => p.endsWith('/service.yaml'))).toEqual(['services/clamd/service.yaml'])
  })

  it('renders the Fly region and nothing unrendered', () => {
    const toml = files.get('services/clamd/fly.toml')!
    expect(toml).toContain('primary_region = "iad"')
    for (const [p, c] of files) if (p.startsWith('services/clamd/')) expect(c, p).not.toMatch(/\{\{|\}\}/)
  })

  it('is recorded as a component, and sent to Terraform', () => {
    expect(files.get('infrastructure/terraform/terraform.tfvars')).toMatch(
      /enabled_services = \["api", "worker", "clamd"\]/,
    )
    expect(files.get('.koras/project.yaml')).toMatch(/clamd/)
  })

  it('names a Fly app in dev only, as <product>-clamd-<environment>', () => {
    const apps = flyAppNames(ctx).filter((n) => n.includes('clamd'))
    expect(apps).toEqual(['scanshop-clamd-dev'])
  })

  it('does not change what any other service is', () => {
    const plain = render('product', 'scanshop').files
    for (const p of paths) {
      if (p.startsWith('services/clamd/')) continue
      // The files that list the product's components, which is what changed.
      if (/(tfvars|project\.yaml|README\.md|CLAUDE\.md|Makefile|pyproject\.toml)$/.test(p)) continue
      expect(files.get(p), p).toBe(plain.get(p))
    }
  })

  it('is excluded from the uv workspace, which refuses a member with no pyproject.toml', () => {
    // `uv lock` failed outright on a generated clamd product -- "Workspace
    // member services/clamd is missing a pyproject.toml" -- and nothing else in
    // this suite could see it, because nothing runs uv on a generated product.
    expect(files.get('pyproject.toml')).toMatch(/exclude = \["services\/clamd"\]/)
    expect(render('product', 'plainuv').files.get('pyproject.toml')).not.toContain('services/clamd')
  })

  it('is unavailable to the control plane, which has no such component', () => {
    expect(() => ctxFor('control-plane', 'cp', ['clamd'])).toThrow(/Unknown component "clamd"/)
  })

  it('has the scripts the workflow calls, in the shared layer', () => {
    for (const s of ['service-descriptor.sh', 'service-secrets.sh', 'verify-private-service.sh']) {
      expect(files.has(`local/scripts/${s}`), s).toBe(true)
    }
  })
})

describe('generation is deterministic and drift-clean', () => {
  it('renders byte-identically twice', () => {
    expect(digest(render('product', 'detshop', ['clamd']).files)).toBe(
      digest(render('product', 'detshop', ['clamd']).files),
    )
    expect(digest(render('product', 'detplain').files)).toBe(digest(render('product', 'detplain').files))
  })

  it('differs by exactly the clamd paths and the files that list components', () => {
    const a = render('product', 'samename').files
    const b = render('product', 'samename', ['clamd']).files
    const differing = [...new Set([...a.keys(), ...b.keys()])].filter((p) => a.get(p) !== b.get(p)).sort()
    // Each of these LISTS the product's components, or (pyproject) has to
    // exclude the one service that is not a Python package.
    expect(differing.filter((p) => !p.startsWith('services/clamd/'))).toEqual([
      '.koras/project.yaml',
      'CLAUDE.md',
      'Makefile',
      'README.md',
      'infrastructure/terraform/terraform.tfvars',
      'pyproject.toml',
    ])
  })

  it('reports no drift for a freshly written clamd project, and sees an edit to its config', { timeout: 180_000 }, async () => {
    const ctx = ctxFor('product', 'driftscan', ['clamd'])
    await writeFiles(ctx, renderTemplate(ctx))
    const root = join(ROOT, 'driftscan')
    expect(checkDrift(ctx, root).findings).toEqual([])

    const conf = join(root, 'services', 'clamd', 'clamd.conf')
    writeFileSync(conf, readFileSync(conf, 'utf8').replace('MaxRecursion 8', 'MaxRecursion 17'))
    const report = checkDrift(ctx, root, { all: true })
    const mentioned = JSON.stringify([...report.findings, ...(report.reviewable ?? [])])
    expect(mentioned).toContain('services/clamd/clamd.conf')
  })

  it('refreshes a drifted clamd file back, and a second refresh changes nothing', { timeout: 180_000 }, async () => {
    const ctx = ctxFor('product', 'refreshscan', ['clamd'])
    await writeFiles(ctx, renderTemplate(ctx))
    const root = join(ROOT, 'refreshscan')
    const conf = join(root, 'services', 'clamd', 'clamd.conf')
    const pristine = readFileSync(conf, 'utf8')
    writeFileSync(conf, pristine + '\n# local edit\n')

    const first = await refreshRenderedPaths(ctx, root, ['services/clamd/clamd.conf'])
    expect(readFileSync(conf, 'utf8')).toBe(pristine)
    expect(JSON.stringify(first)).toContain('clamd.conf')

    const second = await refreshRenderedPaths(ctx, root, ['services/clamd/clamd.conf'])
    expect(readFileSync(conf, 'utf8')).toBe(pristine)
    expect(JSON.stringify(second)).not.toBe(JSON.stringify(first))
  })
})

describe('the Terraform modules cannot give clamd a public address or URL', () => {
  const fly = (f: string) => readFileSync(join(MODULES, 'fly', f), 'utf8')
  const strip = (s: string) =>
    s
      .split('\n')
      .filter((l) => !l.trim().startsWith('#') && !l.trim().startsWith('//'))
      .join('\n')

  it('allocates no IP address anywhere', () => {
    for (const f of ['main.tf', 'outputs.tf', 'variables.tf']) {
      expect(strip(fly(f)), f).not.toMatch(/resource\s+"fly_ip"|fly_ip\b|ip_address|resource\s+"fly_(cert|machine)"/)
    }
  })

  it('creates apps only from the descriptor-driven matrix', () => {
    const main = strip(fly('main.tf'))
    expect(main).toMatch(/for_each\s*=\s*local\.app_matrix/)
    expect(main).toMatch(/module\.eligibility\.matrix/)
    // The old rule -- every service in every environment -- is gone.
    expect(main).not.toMatch(/setproduct\(var\.services, var\.environments\)/)
  })

  it('does not publish a URL for a private service', () => {
    const out = strip(fly('outputs.tf'))
    expect(out).toMatch(/private_services/)
    expect(out).toMatch(/!contains\(module\.eligibility\.private_services/)
  })

  it('is wired to the generated project\'s own services directory', () => {
    const main = readFileSync(join(MODULES, 'project-bootstrap', 'main.tf'), 'utf8')
    expect(main).toMatch(/services_dir\s*=\s*"\$\{path\.root\}\/\.\.\/\.\.\/services"/)
  })

  it('the product root outputs no clamd URL', () => {
    const tf = readFileSync(
      templatePath('product', 'infrastructure', 'terraform', 'main.tf.hbs'),
      'utf8',
    )
    expect(tf.toLowerCase()).not.toContain('clamd')
  })
})

describe('the deploy workflow names no service', () => {
  const wf = readFileSync(templatePath('product', '.github', 'workflows', 'deploy.yml'), 'utf8').replace(/\r\n/g, '\n')
  const live = wf
    .split('\n')
    .filter((l) => !l.trim().startsWith('#'))
    .join('\n')

  it('has no clamd conditional, name or special case', () => {
    expect(live.toLowerCase()).not.toContain('clamd')
  })

  it('discovers services through the descriptor script, not a hardcoded rule', () => {
    expect(live).toMatch(/local\/scripts\/service-descriptor\.sh eligible "\$ENVIRONMENT" services/)
    // The old inline discovery is gone: one rule, in one place.
    expect(live).not.toMatch(/-exec test -f '\{\}\/Dockerfile'/)
  })

  it('applies and verifies secret policy through the script for every service', () => {
    expect(live).toMatch(/service-secrets\.sh apply/)
    expect(live).toMatch(/service-secrets\.sh verify/)
    expect(live).toMatch(/verify-private-service\.sh/)
    // The import it replaces is no longer inline.
    expect(live).not.toMatch(/flyctl secrets import/)
  })

  it('applies the policy BEFORE the deploy, and verifies AFTER it', () => {
    const at = (s: string) => wf.indexOf(s)
    expect(at('service-secrets.sh apply')).toBeGreaterThan(-1)
    expect(at('service-secrets.sh apply')).toBeLessThan(at('flyctl deploy'))
    expect(at('service-secrets.sh verify')).toBeGreaterThan(at('flyctl deploy'))
    expect(at('verify-private-service.sh')).toBeGreaterThan(at('flyctl deploy'))
  })

  it('is the same file for both profiles (it is shared, never rendered)', () => {
    expect(templatePath('control-plane', '.github', 'workflows', 'deploy.yml')).toBe(
      templatePath('product', '.github', 'workflows', 'deploy.yml'),
    )
  })
})

describe('registration names a service only where it is deployed', () => {
  // The registry PRUNES by this list. One that named clamd in test, stg and prod
  // -- where it is never deployed -- would make reconciliation report drift
  // nobody caused.
  const outputs = parseTerraformOutputs(
    JSON.stringify({
      github_repository_full_name: { value: 'KORAS-Technologies/scanshop' },
      doppler_project_name: { value: 'scanshop' },
      supabase_project_refs: { value: {} },
      zitadel_project_ids: { value: {} },
      vercel_project_ids: { value: {} },
      fly_app_names: { value: { 'api-dev': 'scanshop-api-dev', 'clamd-dev': 'scanshop-clamd-dev' } },
    }),
  )

  it('lists clamd in dev and in no other environment', () => {
    const payload = buildRegistration(ctxFor('product', 'scanshop', ['clamd']), outputs)
    expect(payload.environments.dev.services).toContain('clamd')
    for (const env of ['test', 'stg', 'prod']) {
      expect(payload.environments[env].services, env).not.toContain('clamd')
      expect(payload.environments[env].services, env).toContain('api')
    }
  })

  it('leaves every other service in every environment, as before', () => {
    const payload = buildRegistration(ctxFor('product', 'plain'), outputs)
    for (const env of ['dev', 'test', 'stg', 'prod']) {
      expect(payload.environments[env].services).toEqual(['api', 'worker'])
    }
  })
})
