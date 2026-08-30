import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, writeFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import {
  provision,
  readOutputs,
  shouldUseDoppler,
  stateLockRecovery,
  summarisePlan,
} from '../src/terraform/runner.js'
import { formatMissingInputs } from '../src/terraform/inputs.js'
import type { CommandExecutor } from '../src/terraform/runner.js'
import {
  preflightInputs,
  formatMissingInputs,
  generatorProvidedInputs,
  readProjectTfvars,
  resolveTerraformEnv,
  allInputs,
  assembleZitadelInstances,
  assembleSupabaseEnvironments,
  ENVIRONMENTS,
  PROVIDER_CREDENTIALS,
  SECRET_VARIABLES,
  ACCOUNT_VARIABLES,
} from '../src/terraform/inputs.js'
import { confirmApply } from '../src/terraform/approval.js'
import { readBackendConfig, checkExecutionMode } from '../src/terraform/backend.js'
import { parseTerraformOutputs, groupByEnvironment } from '../src/terraform/outputs.js'

const ROOT = join(tmpdir(), `koras-tf-${process.pid}-${Date.now()}`)
const PROJECT_ROOT = join(ROOT, 'sampleapp')

beforeAll(() => {
  // provision() refuses to run against a project that was never generated
  mkdirSync(join(PROJECT_ROOT, 'infrastructure', 'terraform'), { recursive: true })
})

afterAll(() => {
  if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true })
})

function ctxFor(profile: ProfileName = 'product') {
  const { manifest, defaults } = loadProfile(profile)
  return buildContext({
    projectName: 'sampleapp',
    projectSlug: 'sampleapp',
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: ROOT,
    dryRun: false,
    provision: true,
  })
}

/** Every credential and variable preflight requires, under canonical names. */
function completeEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const c of PROVIDER_CREDENTIALS) env[c.name] = 'token-value'
  for (const v of SECRET_VARIABLES) env[v.name] = '{}'
  for (const v of ACCOUNT_VARIABLES) env[v.name] = 'value'
  return env
}

/** The same set, stored the only way Doppler permits: uppercase. */
function dopplerEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const input of allInputs()) env[input.alias ?? input.name] = 'value'
  return env
}

interface Call {
  command: string
  args: string[]
}

function recordingExec(
  calls: Call[],
  responses: Record<string, { exitCode?: number; stdout?: string }> = {},
): CommandExecutor {
  return async (command, args) => {
    calls.push({ command, args })
    const subcommand = args.find((a) => !a.startsWith('-') && a !== 'run' && a !== 'terraform')
    const response = responses[subcommand ?? ''] ?? {}
    return { exitCode: response.exitCode ?? 0, stdout: response.stdout ?? '' }
  }
}

const APPLY_OUTPUTS = JSON.stringify({
  github_repository_full_name: { value: 'koras-technologies/sampleapp' },
  github_repository_url: { value: 'https://github.com/koras-technologies/sampleapp' },
  doppler_project_name: { value: 'sampleapp' },
  supabase_project_refs: { value: { dev: 'abc-dev', prod: 'abc-prod' } },
  zitadel_project_ids: { value: { dev: '123', prod: '456' } },
  vercel_project_ids: { value: { web: 'prj_1' } },
  fly_app_names: { value: { 'api-dev': 'sampleapp-api-dev', 'api-prod': 'sampleapp-api-prod' } },
  supabase_service_role_keys: { value: 'SUPER-SECRET', sensitive: true },
})

// ── preflight ────────────────────────────────────────────────────────────────

describe('credential preflight', () => {
  it('reports every missing input at once', () => {
    const result = preflightInputs({})
    expect(result.ok).toBe(false)
    expect(result.missing).toHaveLength(
      PROVIDER_CREDENTIALS.length + SECRET_VARIABLES.length + ACCOUNT_VARIABLES.length,
    )
  })

  it('names the provider each credential belongs to', () => {
    const message = formatMissingInputs(preflightInputs({}).missing)
    expect(message).toContain('GITHUB_TOKEN')
    // reported under the uppercase name, because that is what Doppler can store
    expect(message).toContain('TF_VAR_ZITADEL_INSTANCES')
    expect(message).toContain('doppler run')
  })

  it('treats a blank value as missing', () => {
    const env = { ...completeEnv(), FLY_API_TOKEN: '   ' }
    expect(preflightInputs(env).missing.map((m) => m.name)).toEqual(['FLY_API_TOKEN'])
  })

  it('passes when everything is set', () => {
    expect(preflightInputs(completeEnv()).ok).toBe(true)
  })

  it('stops before running Terraform when inputs are missing', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: {},
      exec: recordingExec(calls),
    })
    expect(result.status).toBe('missing-inputs')
    expect(calls).toHaveLength(0)
  })
})

// ── Doppler name aliases ─────────────────────────────────────────────────────

describe('uppercase aliases', () => {
  it('accepts inputs stored under the uppercase name Doppler allows', () => {
    expect(preflightInputs(dopplerEnv()).ok).toBe(true)
  })

  it('maps aliases to the case-sensitive names Terraform reads', () => {
    const resolved = resolveTerraformEnv({
      TF_VAR_GITHUB_ORG: 'koras-technologies',
      TF_TOKEN_APP_TERRAFORM_IO: 'atlas-token',
      TF_VAR_ZITADEL_INSTANCES: '{"dev":{}}',
    })
    expect(resolved.TF_VAR_github_org).toBe('koras-technologies')
    expect(resolved.TF_TOKEN_app_terraform_io).toBe('atlas-token')
    expect(resolved.TF_VAR_zitadel_instances).toBe('{"dev":{}}')
  })

  it('removes the alias so it cannot shadow the canonical name', () => {
    // Windows env names are case-insensitive: leaving both in the child env
    // makes the alias win, and Terraform then looks for a variable literally
    // named GITHUB_ORG.
    const resolved = resolveTerraformEnv({ TF_VAR_GITHUB_ORG: 'koras-technologies' })
    expect(resolved.TF_VAR_github_org).toBe('koras-technologies')
    expect('TF_VAR_GITHUB_ORG' in resolved).toBe(false)
  })

  it('drops the alias even when the canonical name was set explicitly', () => {
    const resolved = resolveTerraformEnv({
      TF_VAR_github_org: 'explicit',
      TF_VAR_GITHUB_ORG: 'from-doppler',
    })
    expect(resolved.TF_VAR_github_org).toBe('explicit')
    expect('TF_VAR_GITHUB_ORG' in resolved).toBe(false)
  })

  it('leaves provider tokens, which have no alias, untouched', () => {
    const resolved = resolveTerraformEnv({ GITHUB_TOKEN: 'ghp' })
    expect(resolved.GITHUB_TOKEN).toBe('ghp')
  })

  it('never overrides a canonical name that is already set', () => {
    const resolved = resolveTerraformEnv({
      TF_VAR_github_org: 'explicit',
      TF_VAR_GITHUB_ORG: 'from-doppler',
    })
    expect(resolved.TF_VAR_github_org).toBe('explicit')
  })

  it('reports the uppercase name when an input is missing', () => {
    const message = formatMissingInputs(preflightInputs({}).missing)
    expect(message).toContain('TF_VAR_GITHUB_ORG')
    expect(message).toContain('TF_TOKEN_APP_TERRAFORM_IO')
  })

  it('spawns Terraform with the canonical names resolved', async () => {
    const seen: NodeJS.ProcessEnv[] = []
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: dopplerEnv(),
      exec: async (_c, _a, { env }) => {
        seen.push(env)
        return { exitCode: 0, stdout: '' }
      },
    })
    expect(seen[0].TF_VAR_github_org).toBe('value')
    expect(seen[0].TF_TOKEN_app_terraform_io).toBe('value')
  })
})

// ── flat per-environment secrets ─────────────────────────────────────────────

describe('flat per-environment secrets', () => {
  /** Everything except the two map variables, which are supplied flat below. */
  function baseEnv(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {}
    for (const input of allInputs()) {
      if (input.flat) continue
      env[input.alias ?? input.name] = 'value'
    }
    return env
  }

  function flatZitadel(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {}
    for (const e of ENVIRONMENTS) {
      env[`ZITADEL_${e.toUpperCase()}_DOMAIN`] = `auth-${e}.korastechnologies.com`
      env[`ZITADEL_${e.toUpperCase()}_SERVICE_ACCOUNT_KEY_JSON`] = `{"type":"serviceaccount","env":"${e}"}`
    }
    return env
  }

  function flatSupabase(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {}
    for (const e of ENVIRONMENTS) env[`SUPABASE_DB_PASSWORD_${e.toUpperCase()}`] = `pw-${e}`
    return env
  }

  it('assembles the ZITADEL map from per-instance secrets', () => {
    const json = assembleZitadelInstances(flatZitadel())!
    const parsed = JSON.parse(json)
    expect(Object.keys(parsed)).toEqual(['dev', 'test', 'stg', 'prod'])
    expect(parsed.dev).toEqual({
      domain: 'auth-dev.korastechnologies.com',
      port: 443,
      insecure: false,
      jwt_profile_json: '{"type":"serviceaccount","env":"dev"}',
    })
  })

  it('strips a pasted scheme or trailing slash from the domain', () => {
    const env = flatZitadel()
    env.ZITADEL_DEV_DOMAIN = 'https://auth-dev.korastechnologies.com/'
    expect(JSON.parse(assembleZitadelInstances(env)!).dev.domain).toBe(
      'auth-dev.korastechnologies.com',
    )
  })

  it('honours port and insecure overrides for self-hosted instances', () => {
    const env = { ...flatZitadel(), ZITADEL_DEV_PORT: '8080', ZITADEL_DEV_INSECURE: 'true' }
    const dev = JSON.parse(assembleZitadelInstances(env)!).dev
    expect(dev.port).toBe(8080)
    expect(dev.insecure).toBe(true)
  })

  it('assembles Supabase environments, region optional', () => {
    const parsed = JSON.parse(assembleSupabaseEnvironments(flatSupabase())!)
    expect(parsed.dev).toEqual({ db_password: 'pw-dev' })
    const withRegion = { ...flatSupabase(), SUPABASE_REGION_DEV: 'us-west-1' }
    expect(JSON.parse(assembleSupabaseEnvironments(withRegion)!).dev).toEqual({
      db_password: 'pw-dev',
      region: 'us-west-1',
    })
  })

  it('assembles nothing when an environment is incomplete', () => {
    const partial = flatZitadel()
    delete partial.ZITADEL_STG_SERVICE_ACCOUNT_KEY_JSON
    expect(assembleZitadelInstances(partial)).toBeUndefined()
  })

  it('satisfies preflight without the blob form', () => {
    const env = { ...baseEnv(), ...flatZitadel(), ...flatSupabase() }
    expect(preflightInputs(env).ok).toBe(true)
  })

  it('still accepts the blob form', () => {
    expect(preflightInputs(dopplerEnv()).ok).toBe(true)
  })

  it('prefers an explicit blob over assembly', () => {
    const env = { ...baseEnv(), ...flatZitadel(), ...flatSupabase() }
    env.TF_VAR_ZITADEL_INSTANCES = '{"dev":{"domain":"explicit"}}'
    const resolved = resolveTerraformEnv(env)
    expect(JSON.parse(resolved.TF_VAR_zitadel_instances!).dev.domain).toBe('explicit')
  })

  it('hands Terraform an assembled map', async () => {
    const seen: NodeJS.ProcessEnv[] = []
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: { ...baseEnv(), ...flatZitadel(), ...flatSupabase() },
      exec: async (_c, _a, { env }) => {
        seen.push(env)
        return { exitCode: 0, stdout: '' }
      },
    })
    const instances = JSON.parse(seen[0].TF_VAR_zitadel_instances!)
    expect(instances.prod.domain).toBe('auth-prod.korastechnologies.com')
  })

  it('names the flat alternative when the value is missing entirely', () => {
    const message = formatMissingInputs(preflightInputs({}).missing)
    expect(message).toContain('SUPABASE_DB_PASSWORD_DEV')
    expect(message).toContain('ZITADEL_DEV_DOMAIN')
  })
})

// ── dry run ──────────────────────────────────────────────────────────────────

describe('--provision --dry-run', () => {
  it('runs init and plan, then stops', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls, {
        plan: { stdout: 'Plan: 12 to add, 0 to change, 0 to destroy.' },
      }),
    })

    expect(result.status).toBe('planned')
    expect(calls.map((c) => c.args[0])).toEqual(['init', 'plan'])
    expect(calls.some((c) => c.args.includes('apply'))).toBe(false)
  })

  it('never prompts for approval', async () => {
    const ask = vi.fn(async () => 'yes')
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([]),
      approval: { ask, isTTY: true },
    })
    expect(ask).not.toHaveBeenCalled()
  })
})

// ── approval gate ────────────────────────────────────────────────────────────

describe('approval gate', () => {
  it('applies only after the operator types "yes" in full', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls, { output: { stdout: APPLY_OUTPUTS } }),
      approval: { ask: async () => 'yes', isTTY: true },
    })

    expect(result.status).toBe('applied')
    expect(calls.map((c) => c.args[0])).toEqual(['init', 'plan', 'apply', 'output'])
  })

  it('applies the saved plan file, so what was approved is what runs', async () => {
    const calls: Call[] = []
    await provision(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls, { output: { stdout: APPLY_OUTPUTS } }),
      approval: { ask: async () => 'yes', isTTY: true },
    })
    const apply = calls.find((c) => c.args[0] === 'apply')!
    const plan = calls.find((c) => c.args[0] === 'plan')!

    // The same file that was planned is the file that is applied, so what the
    // operator approved is exactly what runs.
    const planned = plan.args.find((a) => a.startsWith('-out='))!.slice('-out='.length)
    expect(apply.args).toContain(planned)

    // And it lives outside the generated project. A plan embeds a full state
    // snapshot -- every credential Terraform touched -- and the very next thing
    // this CLI does is `git add .` and push, so a plan inside the project is a
    // plan published to GitHub.
    expect(planned.startsWith(PROJECT_ROOT)).toBe(false)
    expect(planned).not.toContain('infrastructure')
  })

  for (const answer of ['y', 'Y', 'YES', 'no', '', ' ']) {
    it(`refuses to apply on ${answer.trim() === '' ? 'an empty answer' : `"${answer}"`}`, async () => {
      const calls: Call[] = []
      const result = await provision(ctxFor(), {
        dryRun: false,
        projectRoot: PROJECT_ROOT,
        env: completeEnv(),
        exec: recordingExec(calls),
        approval: { ask: async () => answer, isTTY: true },
      })

      expect(result.status).toBe('declined')
      expect(calls.some((c) => c.args[0] === 'apply')).toBe(false)
    })
  }

  it('refuses to apply without an interactive terminal', async () => {
    expect(
      await confirmApply(
        { projectName: 'sampleapp', projectSlug: 'sampleapp', profile: 'product' },
        { isTTY: false },
      ),
    ).toBe(false)
  })
})

// ── failure handling ─────────────────────────────────────────────────────────

describe('failure handling', () => {
  it('does not plan when init fails', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls, { init: { exitCode: 1 } }),
    })
    expect(result.status).toBe('init-failed')
    expect(calls).toHaveLength(1)
  })

  it('does not ask for approval when plan fails', async () => {
    const ask = vi.fn(async () => 'yes')
    const result = await provision(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], { plan: { exitCode: 1 } }),
      approval: { ask, isTTY: true },
    })
    expect(result.status).toBe('plan-failed')
    expect(ask).not.toHaveBeenCalled()
  })

  it('fails clearly when the project was never generated', async () => {
    await expect(
      provision(ctxFor(), {
        dryRun: true,
        projectRoot: join(ROOT, 'does-not-exist'),
        env: completeEnv(),
        exec: recordingExec([]),
      }),
    ).rejects.toThrow(/No Terraform configuration/)
  })
})

// ── Doppler integration ──────────────────────────────────────────────────────

describe('Doppler', () => {
  it('is used when a project and config are configured', () => {
    expect(shouldUseDoppler({ DOPPLER_PROJECT: 'koras-platform-bootstrap', DOPPLER_CONFIG: 'dev' })).toBe(true)
    expect(shouldUseDoppler({ DOPPLER_PROJECT: 'koras-platform-bootstrap' })).toBe(false)
    expect(shouldUseDoppler({})).toBe(false)
  })

  it('wraps Terraform in `doppler run --` when the inputs are not in this environment', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      // Doppler configured, but nothing injected into this process
      env: { DOPPLER_PROJECT: 'koras-platform-bootstrap', DOPPLER_CONFIG: 'prod' },
      exec: recordingExec(calls),
    })
    expect(result.status).toBe('planned')
    expect(calls[0].command).toBe('doppler')
    expect(calls[0].args.slice(0, 3)).toEqual(['run', '--', 'terraform'])
  })

  it('does not nest a second doppler run when the inputs are already present', async () => {
    // `doppler run` injects DOPPLER_PROJECT/DOPPLER_CONFIG into the child, so
    // this is the normal case: the generator itself was invoked under Doppler.
    const calls: Call[] = []
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: { ...completeEnv(), DOPPLER_PROJECT: 'koras-platform-bootstrap', DOPPLER_CONFIG: 'prod' },
      exec: recordingExec(calls),
    })
    expect(calls[0].command).toBe('terraform')
  })

  it('falls back to plain terraform when Doppler is not configured', async () => {
    const calls: Call[] = []
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls),
    })
    expect(calls[0].command).toBe('terraform')
  })
})

// ── generator → Terraform contract ───────────────────────────────────────────

describe('generator inputs', () => {
  it('passes the profile to Terraform', () => {
    expect(generatorProvidedInputs(ctxFor('product')).profile).toBe('product')
    expect(generatorProvidedInputs(ctxFor('control-plane')).profile).toBe('control-plane')
  })

  it('passes only enabled components', () => {
    const inputs = generatorProvidedInputs(ctxFor('product'))
    expect(inputs.enabled_apps).toEqual(['web', 'admin'])
    expect(inputs.enabled_services).toEqual(['api', 'worker'])
  })

  it('passes control-plane component keys, not directory names', () => {
    const inputs = generatorProvidedInputs(ctxFor('control-plane'))
    expect(inputs.enabled_apps).toEqual(['platform_admin', 'portal'])
    expect(inputs.enabled_services).toEqual(['api', 'worker', 'scheduler'])
  })
})

// ── outputs ──────────────────────────────────────────────────────────────────

describe('outputs', () => {
  const outputs = parseTerraformOutputs(APPLY_OUTPUTS)

  it('extracts non-secret infrastructure references', () => {
    expect(outputs.githubRepository).toBe('koras-technologies/sampleapp')
    expect(outputs.supabaseProjectRefs.dev).toBe('abc-dev')
    expect(outputs.flyApps).toEqual(['sampleapp-api-dev', 'sampleapp-api-prod'])
  })

  it('withholds sensitive outputs, recording only the name', () => {
    expect(outputs.withheld).toEqual(['supabase_service_role_keys'])
    expect(JSON.stringify(outputs)).not.toContain('SUPER-SECRET')
  })

  it('groups references by environment for registration', () => {
    const grouped = groupByEnvironment(outputs, 'sampleapp', ['dev', 'prod'])
    expect(grouped[0]).toEqual({
      environment: 'dev',
      dopplerProject: 'sampleapp-dev',
      supabaseProject: 'abc-dev',
      flyApps: ['sampleapp-api-dev'],
    })
  })

  it('reports a parse failure rather than returning empty references', () => {
    expect(() => parseTerraformOutputs('not json')).toThrow(/Could not parse/)
  })
})

// ── provisioning an existing project ─────────────────────────────────────────

describe('--provision-only', () => {
  const EXISTING = join(ROOT, 'existing')
  const TFVARS = `profile      = "product"
project_name = "existing"
project_slug = "existing"

enabled_apps     = ["web","marketing"]
enabled_services = ["api","scheduler"]
`

  beforeAll(() => {
    mkdirSync(join(EXISTING, 'infrastructure', 'terraform'), { recursive: true })
    writeFileSync(join(EXISTING, 'infrastructure', 'terraform', 'terraform.tfvars'), TFVARS)
  })

  it('reads component selections from the project on disk', () => {
    const parsed = readProjectTfvars(TFVARS)
    expect(parsed.profile).toBe('product')
    expect(parsed.projectSlug).toBe('existing')
    // deliberately different from what today's profile defaults produce
    expect(parsed.enabledApps).toEqual(['web', 'marketing'])
    expect(parsed.enabledServices).toEqual(['api', 'scheduler'])
  })

  it('provisions without regenerating', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: EXISTING,
      env: completeEnv(),
      exec: recordingExec(calls),
    })
    expect(result.status).toBe('planned')
    expect(calls.map((c) => c.args[0])).toEqual(['init', 'plan'])
  })

  it('refuses when the requested profile differs from the one on disk', async () => {
    const calls: Call[] = []
    const result = await provision(ctxFor('control-plane'), {
      dryRun: true,
      projectRoot: EXISTING,
      env: completeEnv(),
      exec: recordingExec(calls),
    })
    expect(result.status).toBe('profile-mismatch')
    expect(calls).toHaveLength(0)
  })

  it('tolerates a project with no tfvars yet', () => {
    const parsed = readProjectTfvars('# nothing here')
    expect(parsed.profile).toBeUndefined()
    expect(parsed.enabledApps).toEqual([])
  })
})

// ── HCP execution mode ───────────────────────────────────────────────────────

describe('HCP execution mode', () => {
  const BACKEND = `terraform {
  backend "remote" {
    organization = "koras"

    workspaces {
      name = "docoris"
    }
  }
}`

  const respond = (status: number, body: unknown) => async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })

  it('reads organization and workspace from backend.tf', () => {
    expect(readBackendConfig(BACKEND)).toEqual({ organization: 'koras', workspace: 'docoris' })
  })

  it('ignores a configuration with no remote backend', () => {
    expect(readBackendConfig('terraform {}')).toBeUndefined()
  })

  it('passes when the workspace runs locally', async () => {
    const result = await checkExecutionMode(
      { organization: 'koras', workspace: 'docoris' },
      'token',
      respond(200, { data: { attributes: { 'execution-mode': 'local' } } }),
    )
    expect(result.status).toBe('local')
  })

  it('explains how to fix remote execution', async () => {
    const result = await checkExecutionMode(
      { organization: 'koras', workspace: 'docoris' },
      'token',
      respond(200, { data: { attributes: { 'execution-mode': 'remote' } } }),
    )
    expect(result.status).toBe('remote')
    if (result.status !== 'remote') return
    expect(result.message).toMatch(/Execution Mode → Local/)
    expect(result.message).toMatch(/app\.terraform\.io\/app\/koras\/workspaces\/docoris/)
  })

  it('does not block when the workspace does not exist yet', async () => {
    const result = await checkExecutionMode(
      { organization: 'koras', workspace: 'docoris' },
      'token',
      respond(404, {}),
    )
    expect(result.status).toBe('unknown')
  })

  it('does not block when HCP is unreachable', async () => {
    const result = await checkExecutionMode(
      { organization: 'koras', workspace: 'docoris' },
      'token',
      async () => {
        throw new Error('offline')
      },
    )
    expect(result.status).toBe('unknown')
  })

  it('stops before plan when the workspace is remote', async () => {
    writeFileSync(join(PROJECT_ROOT, 'infrastructure', 'terraform', 'backend.tf'), BACKEND)
    const calls: Call[] = []
    const result = await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls),
      fetchImpl: respond(200, { data: { attributes: { 'execution-mode': 'remote' } } }),
    })
    expect(result.status).toBe('remote-execution')
    expect(calls.map((c) => c.args[0])).toEqual(['init'])
    rmSync(join(PROJECT_ROOT, 'infrastructure', 'terraform', 'backend.tf'))
  })
})

describe('plan summary', () => {
  it('pulls the Plan: line out of Terraform output', () => {
    expect(summarisePlan('noise\nPlan: 12 to add, 0 to change, 0 to destroy.\nmore')).toBe(
      'Plan: 12 to add, 0 to change, 0 to destroy.',
    )
  })

  it('is undefined when Terraform reported no plan line', () => {
    expect(summarisePlan('No changes. Infrastructure is up-to-date.')).toBeUndefined()
  })
})

// ── missing-input diagnosis ──────────────────────────────────────────────────

describe('missing inputs name the cause', () => {
  const missing = [{ name: 'GITHUB_TOKEN', detail: 'GitHub — repository' }]

  it('says the command is not running under doppler run', () => {
    const message = formatMissingInputs(missing, {})
    expect(message).toContain('not running under `doppler run`')
    expect(message).toContain('DOPPLER_PROJECT')
  })

  it('blames the config, not the wrapper, when already inside doppler run', () => {
    // DOPPLER_PROJECT is injected by `doppler run`, so its presence means the
    // wrapper was used and the config itself is short of secrets.
    const message = formatMissingInputs(missing, {
      DOPPLER_PROJECT: 'koras-platform-bootstrap',
      DOPPLER_CONFIG: 'prod',
    })
    expect(message).toContain('koras-platform-bootstrap/prod')
    expect(message).toContain('does not define every required secret')
    expect(message).not.toContain('not running under')
  })
})

describe('stateLockRecovery', () => {
  // Verbatim from a real failure against backend "remote". The ID that
  // force-unlock accepts is the one on the `lock ID:` line, not the UUID.
  const LOCK_ERROR = [
    'Error: Error acquiring the state lock',
    '',
    'Error message: workspace already locked (lock ID: "koras/koras-control-plane")',
    'Lock Info:',
    '  ID:        d2962922-f092-3cf6-98e4-3ac2df00b3cd',
    '  Operation: OperationTypePlan',
  ].join('\n')

  it('recovers the backend lock ID, not the Lock Info UUID', () => {
    const msg = stateLockRecovery(LOCK_ERROR)
    expect(msg).toContain('terraform force-unlock koras/koras-control-plane')
    expect(msg).not.toContain('d2962922')
  })

  it('prefixes the command with doppler run when Terraform was wrapped', () => {
    expect(stateLockRecovery(LOCK_ERROR, true)).toContain(
      'doppler run -- terraform force-unlock koras/koras-control-plane',
    )
  })

  it('stays quiet for failures that are not lock failures', () => {
    expect(stateLockRecovery('Error: Invalid provider configuration')).toBeUndefined()
    expect(stateLockRecovery('')).toBeUndefined()
    expect(stateLockRecovery(undefined)).toBeUndefined()
  })
})

// ── reading outputs without touching the estate ──────────────────────────────

describe('readOutputs, which backs --register-only', () => {
  /**
   * The property that makes this usable on a live estate, and the only one
   * worth guarding structurally: there is no path from here to a plan or an
   * apply. A regression that reintroduced one would not fail any other test —
   * it would simply make `--register-only` capable of changing infrastructure,
   * quietly, which is the failure this whole flag exists to avoid.
   */
  it('runs init and output, and never plan or apply', async () => {
    const calls: Call[] = []
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec(calls, { output: { stdout: APPLY_OUTPUTS } }),
    })

    expect(result.status).toBe('read')
    const subcommands = calls.map((c) => c.args[0])
    expect(subcommands).toEqual(['init', 'output'])
    expect(subcommands).not.toContain('plan')
    expect(subcommands).not.toContain('apply')
  })

  /**
   * The teardown case, and the reason this check exists at all.
   *
   * `terraform output -json` answers `{}` for a destroyed workspace exactly as
   * it does for one never applied, and the parser turns that into a valid
   * all-empty result rather than an error. The payload built from it is then
   * *accepted*: identity comes from the manifest, so the Control Plane answers
   * 200 and the operator is told a torn-down product was registered.
   */
  it('refuses an empty workspace rather than registering a torn-down product', async () => {
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], { output: { stdout: '{}' } }),
    })
    expect(result.status).toBe('empty-state')
  })

  /**
   * A state consisting entirely of sensitive outputs is a real estate. The
   * parser withholds those values, so a check that looked only at what it could
   * read would call it empty and refuse a legitimate re-registration.
   */
  it('treats a state of nothing but withheld secrets as real infrastructure', async () => {
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], {
        output: { stdout: JSON.stringify({ some_secret: { value: 'x', sensitive: true } }) },
      }),
    })
    expect(result.status).toBe('read')
  })

  it('parses the references registration will send', async () => {
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], { output: { stdout: APPLY_OUTPUTS } }),
    })
    expect(result.status).toBe('read')
    if (result.status !== 'read') return
    expect(result.outputs.githubRepository).toBe('koras-technologies/sampleapp')
  })

  it('reports a failed init without pretending it read anything', async () => {
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], { init: { exitCode: 1 } }),
    })
    expect(result.status).toBe('init-failed')
  })

  it('reports a project that was never provisioned rather than sending nothing', async () => {
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: PROJECT_ROOT,
      env: completeEnv(),
      exec: recordingExec([], { output: { exitCode: 1 } }),
    })
    expect(result.status).toBe('output-failed')
  })

  it('refuses a directory holding no Terraform configuration', async () => {
    const calls: Call[] = []
    const result = await readOutputs(ctxFor(), {
      dryRun: false,
      projectRoot: join(ROOT, 'never-generated'),
      env: completeEnv(),
      exec: recordingExec(calls),
    })
    expect(result.status).toBe('no-terraform')
    expect(calls).toHaveLength(0)
  })
})
