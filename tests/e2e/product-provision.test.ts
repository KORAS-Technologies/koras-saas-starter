import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rmSync, existsSync, readFileSync } from 'node:fs'

import { loadProfile } from '../../generators/create-koras-app/src/profiles/index.js'
import { resolveSelections } from '../../generators/create-koras-app/src/profiles/validator.js'
import { buildContext } from '../../generators/create-koras-app/src/generation/context.js'
import { renderTemplate } from '../../generators/create-koras-app/src/generation/engine.js'
import { writeFiles } from '../../generators/create-koras-app/src/generation/writer.js'
import { validateGeneratedProject } from '../../generators/create-koras-app/src/validation/generated-project.js'
import { parseTerraformOutputs } from '../../generators/create-koras-app/src/terraform/outputs.js'
import { runRegistration } from '../../generators/create-koras-app/src/registration/index.js'
import {
  BASE_URL_VAR,
  TOKEN_VAR,
} from '../../generators/create-koras-app/src/registration/config.js'

import { startControlPlaneStub, type ControlPlaneStub } from './helpers/control-plane-stub.js'
import { liveMode, describeLive } from './helpers/live.js'

/**
 * Acceptance scenario: a product is generated, validated, and registered.
 *
 * The whole path a real `--provision` run takes, minus the seven providers.
 * Terraform's contribution is replaced by the JSON it emits — the same string
 * `terraform output -json` produces, including outputs it marked sensitive —
 * because everything downstream of that string is generator logic, and that is
 * what this asserts.
 *
 * The Control Plane is not replaced. It is a real HTTP server on a real port,
 * so registration is exercised over a socket rather than through a function
 * double. That is what makes this an acceptance test rather than a larger unit
 * test, and it is the honest reading of Phase 10's "against a running Control
 * Plane" that does not require an estate to exist.
 *
 * The live variant — the one that does create real infrastructure — is gated
 * behind KORAS_E2E_LIVE and skipped by default. See `helpers/live.ts`.
 */

const OUT = join(tmpdir(), `koras-e2e-product-${process.pid}-${Date.now()}`)
const SLUG = 'koras-e2e-shop'
const TOKEN = 'cp_e2e_8b21f4c7de90a3'

/**
 * What Terraform emits after a successful product apply.
 *
 * The two sensitive entries are the point of including them: the parser must
 * drop them, so no payload built downstream can carry them however it is
 * written.
 */
const TERRAFORM_OUTPUT = JSON.stringify({
  github_repository_full_name: { value: `KORAS-Technologies/${SLUG}` },
  github_repository_url: { value: `https://github.com/KORAS-Technologies/${SLUG}` },
  doppler_project_name: { value: SLUG },
  supabase_project_refs: {
    value: { dev: 'ref-dev', test: 'ref-test', stg: 'ref-stg', prod: 'ref-prod' },
  },
  zitadel_project_ids: { value: { dev: '1', test: '2', stg: '3', prod: '4' } },
  vercel_project_ids: {
    value: { 'web-dev': 'prj_a', 'admin-dev': 'prj_b', 'web-prod': 'prj_c', 'admin-prod': 'prj_d' },
  },
  fly_app_names: {
    value: {
      'api-dev': `${SLUG}-api-dev`,
      'worker-dev': `${SLUG}-worker-dev`,
      'api-prod': `${SLUG}-api-prod`,
    },
  },
  zitadel_client_ids: { value: { dev: 'client-dev-secret' }, sensitive: true },
  redis_urls: { value: { dev: 'rediss://default:hunter2@example.upstash.io' }, sensitive: true },
})

function productContext() {
  const { manifest, defaults } = loadProfile('product')
  return buildContext({
    projectName: SLUG,
    projectSlug: SLUG,
    profile: 'product',
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: OUT,
    dryRun: false,
    provision: true,
  })
}

let stub: ControlPlaneStub

beforeAll(async () => {
  stub = await startControlPlaneStub({ token: TOKEN })
})

afterAll(async () => {
  await stub?.close()
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

describe('a product is generated and validated', () => {
  const ctx = productContext()
  let fileList: string[]

  beforeAll(() => {
    fileList = writeFiles(ctx, renderTemplate(ctx)).fileList
  })

  it('writes a project that passes the generator own validation', () => {
    // Returns a verdict rather than throwing, so the verdict is what to
    // assert -- and its `error` is what to print when it is a bad one.
    const verdict = validateGeneratedProject({
      projectRoot: join(OUT, SLUG),
      expectedSlug: SLUG,
      expectedProfile: 'product',
    })

    expect(verdict.error ?? null).toBeNull()
    expect(verdict.valid).toBe(true)
    expect(verdict.manifest?.project.profile).toBe('product')
    expect(verdict.manifest?.project.slug).toBe(SLUG)
  })

  it('records its identity in the manifest downstream tooling reads', () => {
    const manifest = readFileSync(join(OUT, SLUG, '.koras', 'project.yaml'), 'utf8')
    expect(manifest).toContain('schema_version: 1')
    expect(manifest).toContain(`slug: ${SLUG}`)
    expect(manifest).toContain('profile: product')
  })

  it('carries the Claude configuration every KORAS repository has', () => {
    expect(fileList).toContain('.claude/CLAUDE.md')
    expect(fileList.some((f) => f.startsWith('.claude/skills/koras-architecture/'))).toBe(true)
    expect(fileList.some((f) => f.startsWith('.claude/skills/koras-profile-product/'))).toBe(true)
    expect(fileList.some((f) => f.startsWith('.claude/skills/koras-profile-control-plane/'))).toBe(
      false,
    )
  })

  it('ships the runtime Control Plane client the product profile enables', () => {
    expect(fileList.some((f) => f.startsWith('packages/control-plane-client/'))).toBe(true)
  })

  it('leaves no template placeholder unrendered', () => {
    const suspicious: string[] = []
    for (const relative of fileList) {
      // `.claude/` is a shared_asset -- copied verbatim, never rendered -- so
      // Handlebars examples inside a vendored skill's documentation are its
      // subject matter rather than leakage.
      if (relative.startsWith('.claude/')) continue

      const full = join(OUT, SLUG, relative)
      if (!existsSync(full)) continue
      let content: string
      try {
        content = readFileSync(full, 'utf8')
      } catch {
        continue
      }

      // An unrendered variable, specifically: `{{name}}` or `{{a.b}}`, and not
      // preceded by `$`. GitHub Actions writes `${{ github.ref }}` and shells
      // write `${VAR:-default}`; neither is Handlebars, and a check that
      // flagged them would have to be switched off to stay green.
      const unrendered = /(?<!\$)\{\{\s*[a-zA-Z_][\w.]*\s*\}\}/
      if (unrendered.test(content) || /__PLACEHOLDER__|TODO_GENERATOR|REPLACE_ME/.test(content)) {
        suspicious.push(relative)
      }
    }
    expect(suspicious).toEqual([])
  })
})

describe('the product registers with a running Control Plane', () => {
  const ctx = productContext()
  const outputs = parseTerraformOutputs(TERRAFORM_OUTPUT)

  // Registered once, then asserted from every angle. Reading `.at(-1)` inside
  // each test would make every assertion depend on the previous test having
  // run and left the right thing behind -- so a single early failure would
  // reappear as a cascade of unrelated ones.
  let report: Awaited<ReturnType<typeof runRegistration>>
  let request: (typeof stub.received)[number]
  let stored: Record<string, unknown>

  beforeAll(async () => {
    report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: TOKEN },
    })
    request = stub.received.at(-1)!
    stored = stub.registered.at(-1) ?? {}
  })

  it('is accepted, and the Control Plane records it', () => {
    expect(report.kind).toBe('registered')
    expect(stub.registered).toHaveLength(1)
    expect(stored.slug).toBe(SLUG)
    expect(stored.profile).toBe('product')
  })

  it('reaches the endpoint the profile declares, over a real socket', () => {
    expect(request.method).toBe('POST')
    expect(request.path).toBe('/api/platform/v1/products')
    expect(request.headers.authorization).toBe(`Bearer ${TOKEN}`)
    expect(request.headers['x-koras-correlation-id']).toBeTruthy()
  })

  it('describes every environment the profile declares', () => {
    const environments = stored.environments as Record<string, unknown>
    expect(Object.keys(environments).sort()).toEqual(['dev', 'prod', 'stg', 'test'])
  })

  it('sends no credential, though Terraform emitted two', () => {
    expect(request.raw).not.toContain('client-dev-secret')
    expect(request.raw).not.toContain('hunter2')
    expect(request.raw).not.toContain(TOKEN)
  })

  it('survives an unreachable Control Plane without unwinding anything', async () => {
    stub.failNext({ status: 503, body: '{"detail":"upstream unavailable"}' })
    const report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: TOKEN },
    })

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(true)
  })

  it('does not retry a payload the Control Plane refused', async () => {
    const before = stub.received.length
    stub.failNext({ status: 422, body: '{"detail":"extra fields not permitted: nope"}' })
    const report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: TOKEN },
    })

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(false)
    expect(stub.received.length).toBe(before + 1)
  })

  it('is refused outright by a Control Plane that does not know the token', async () => {
    const report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: 'cp_e2e_wrong_token_value' },
    })

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(false)
  })

  it('registers nothing when the estate has no Control Plane yet', async () => {
    const before = stub.received.length
    const report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      env: { [BASE_URL_VAR]: '', [TOKEN_VAR]: TOKEN },
    })

    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('not-configured')
    expect(stub.received.length).toBe(before)
  })
})

// ── the live variant ─────────────────────────────────────────────────────────

describeLive('a product is provisioned against live infrastructure', () => {
  it('is not implemented as an automated run', () => {
    // Deliberately explicit rather than absent. Phase 13's criterion is a live
    // apply across seven providers with teardown afterwards, and an automated
    // test that creates and destroys a real estate needs an authorisation this
    // repository cannot grant itself. `helpers/teardown.ts` is the half of it
    // that can be written and tested safely; the apply is a runbook step.
    expect(liveMode()).toBe(true)
    throw new Error(
      'Live provisioning acceptance is a manual runbook step — see docs/PROVISIONING_RUNBOOK.md. ' +
        'KORAS_E2E_LIVE is set, but no automated live apply exists.',
    )
  })
})
