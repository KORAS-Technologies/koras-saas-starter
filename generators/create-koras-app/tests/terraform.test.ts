import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, writeFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { provision, shouldUseDoppler, summarisePlan } from '../src/terraform/runner.js'
import type { CommandExecutor } from '../src/terraform/runner.js'
import {
  preflightInputs,
  formatMissingInputs,
  generatorProvidedInputs,
  readProjectTfvars,
  PROVIDER_CREDENTIALS,
  SECRET_VARIABLES,
  ACCOUNT_VARIABLES,
} from '../src/terraform/inputs.js'
import { confirmApply } from '../src/terraform/approval.js'
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

/** Every credential and variable preflight requires, all present. */
function completeEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const c of PROVIDER_CREDENTIALS) env[c.name] = 'token-value'
  for (const v of SECRET_VARIABLES) env[v.name] = '{}'
  for (const v of ACCOUNT_VARIABLES) env[v.name] = 'value'
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
    expect(message).toContain('TF_VAR_zitadel_instances')
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
    expect(apply.args).toContain('tfplan')
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

  it('wraps Terraform in `doppler run --`', async () => {
    const calls: Call[] = []
    await provision(ctxFor(), {
      dryRun: true,
      projectRoot: PROJECT_ROOT,
      env: { ...completeEnv(), DOPPLER_PROJECT: 'koras-platform-bootstrap', DOPPLER_CONFIG: 'dev' },
      exec: recordingExec(calls),
    })
    expect(calls[0].command).toBe('doppler')
    expect(calls[0].args.slice(0, 3)).toEqual(['run', '--', 'terraform'])
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
