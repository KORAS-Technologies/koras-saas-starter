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
import { TOKEN_VAR } from '../../generators/create-koras-app/src/registration/config.js'

import { startControlPlaneStub, type ControlPlaneStub } from './helpers/control-plane-stub.js'
import { liveMode, describeLive } from './helpers/live.js'

/**
 * Acceptance scenario: the Control Plane is generated, and registers nothing.
 *
 * The interesting assertion is a negative one, which is why it gets a real
 * server rather than a mock returning "no calls were made". The stub is
 * listening and would accept a registration; nothing arrives. That
 * distinguishes "the generator did not call" from "the call was made and
 * something swallowed it", which a function double asserting call count cannot.
 *
 * Invariant 2: the Control Plane is the platform authority, not an entry in
 * its own product registry. Three independent things refuse it — the profile
 * manifest here, a validator at the Control Plane's edge, and a database
 * constraint. This covers the first, and the stub covers the second.
 */

const OUT = join(tmpdir(), `koras-e2e-cp-${process.pid}-${Date.now()}`)
const SLUG = 'koras-e2e-control-plane'
const TOKEN = 'cp_e2e_1d5f30ba97c264'

const TERRAFORM_OUTPUT = JSON.stringify({
  github_repository_full_name: { value: `KORAS-Technologies/${SLUG}` },
  doppler_project_name: { value: SLUG },
  supabase_project_refs: { value: { dev: 'ref-dev', prod: 'ref-prod' } },
  zitadel_project_ids: { value: { dev: '1', prod: '4' } },
  vercel_project_ids: { value: { 'platform-admin-dev': 'prj_x' } },
  fly_app_names: { value: { 'api-dev': `${SLUG}-api-dev` } },
})

function controlPlaneContext() {
  const { manifest, defaults } = loadProfile('control-plane')
  return buildContext({
    projectName: SLUG,
    projectSlug: SLUG,
    profile: 'control-plane',
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

describe('the Control Plane is generated and validated', () => {
  const ctx = controlPlaneContext()
  let fileList: string[]

  // Several hundred files through Handlebars and onto disk. Well over the
  // default ten seconds on a slow disk, which is not a defect in the project.
  beforeAll(async () => {
    fileList = (await writeFiles(ctx, renderTemplate(ctx))).fileList
  }, 300_000)

  it('writes a project that passes the generator own validation', () => {
    // Returns a verdict rather than throwing, so the verdict is what to
    // assert -- and its `error` is what to print when it is a bad one.
    const verdict = validateGeneratedProject({
      projectRoot: join(OUT, SLUG),
      expectedSlug: SLUG,
      expectedProfile: 'control-plane',
    })

    expect(verdict.error ?? null).toBeNull()
    expect(verdict.valid).toBe(true)
    expect(verdict.manifest?.project.profile).toBe('control-plane')
    expect(verdict.manifest?.project.slug).toBe(SLUG)
  })

  it('records control-plane, not product, as its profile', () => {
    // The regression that matters most in this repository: a manifest saying
    // `product` would let later tooling run product provisioning against the
    // platform authority.
    const manifest = readFileSync(join(OUT, SLUG, '.koras', 'project.yaml'), 'utf8')
    expect(manifest).toContain('profile: control-plane')
    expect(manifest).not.toContain('profile: product')
  })

  it('carries its own profile skill and not the product one', () => {
    expect(
      fileList.some((f) => f.startsWith('.claude/skills/koras-profile-control-plane/')),
    ).toBe(true)
    expect(fileList.some((f) => f.startsWith('.claude/skills/koras-profile-product/'))).toBe(false)
  })

  it('ships no Control Plane client — it is the authority, not a client', () => {
    expect(fileList.some((f) => f.startsWith('packages/control-plane-client/'))).toBe(false)
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

describe('the Control Plane registers nothing, with a server listening', () => {
  const ctx = controlPlaneContext()
  const outputs = parseTerraformOutputs(TERRAFORM_OUTPUT)

  it('makes zero requests, and says the profile is why', async () => {
    const before = stub.received.length
    const report = await runRegistration(ctx, outputs, {
      skipRequested: false,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: TOKEN },
    })

    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('profile')
    expect(stub.received.length).toBe(before)
    expect(stub.registered).toHaveLength(0)
  })

  it('still makes zero requests when --skip-registration is not the reason', async () => {
    // --skip-registration on a control-plane run overrides nothing. Reporting
    // it as the cause would suggest the flag is what prevented the call, and
    // that removing the flag would cause one.
    const before = stub.received.length
    const report = await runRegistration(ctx, outputs, {
      skipRequested: true,
      provisioned: true,
      urlOverride: stub.baseUrl,
      env: { [TOKEN_VAR]: TOKEN },
    })

    expect(report.kind === 'skipped' && report.reason).toBe('profile')
    expect(stub.received.length).toBe(before)
  })

  it('would be refused by the Control Plane even if the generator did call', async () => {
    // The third refusal, proven rather than assumed: if the guard above ever
    // regressed, this is what the request would meet.
    const response = await fetch(`${stub.baseUrl}/api/platform/v1/products`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify({
        code: SLUG,
        name: SLUG,
        slug: SLUG,
        profile: 'control-plane',
        environments: {},
      }),
    })

    expect(response.status).toBe(422)
    expect(await response.text()).toContain('cannot be registered as a product')
    expect(stub.registered).toHaveLength(0)
  })
})

// ── the live variant ─────────────────────────────────────────────────────────

describeLive('the Control Plane is provisioned against live infrastructure', () => {
  it('is not implemented as an automated run', () => {
    expect(liveMode()).toBe(true)
    throw new Error(
      'Live provisioning acceptance is a manual runbook step — see docs/PROVISIONING_RUNBOOK.md. ' +
        'KORAS_E2E_LIVE is set, but no automated live apply exists.',
    )
  })
})
