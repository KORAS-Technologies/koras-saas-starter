import { describe, it, expect } from 'vitest'
import {
  dopplerUnavailableMessage,
  reexecUnderDoppler,
  resolveDopplerLocation,
  shouldReexecUnderDoppler,
  type Spawner,
} from '../src/terraform/doppler.js'
import { preflightInputs } from '../src/terraform/inputs.js'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'

// Every input preflightInputs asks for, so "already supplied by hand" is
// exercised on its own merits rather than via the re-exec guard.
function envWithInputs(): NodeJS.ProcessEnv {
  return {
    GITHUB_TOKEN: 'x',
    DOPPLER_TOKEN: 'x',
    SUPABASE_ACCESS_TOKEN: 'x',
    VERCEL_API_TOKEN: 'x',
    FLY_API_TOKEN: 'x',
    CLOUDFLARE_API_TOKEN: 'x',
    TF_TOKEN_app_terraform_io: 'x',
    TF_VAR_supabase_environments: '{}',
    TF_VAR_zitadel_instances: '{}',
    TF_VAR_github_org: 'koras',
    TF_VAR_primary_domain: 'example.com',
    TF_VAR_supabase_org_id: 'x',
    TF_VAR_vercel_team_id: 'x',
    TF_VAR_fly_org_slug: 'x',
    TF_VAR_cloudflare_zone_id: 'x',
  }
}

describe('resolveDopplerLocation', () => {
  it('reads the estate location from the profile', () => {
    for (const profile of ['product', 'control-plane'] as ProfileName[]) {
      const { defaults } = loadProfile(profile)
      expect(resolveDopplerLocation(defaults, {})).toEqual({
        project: 'koras-platform-bootstrap',
        config: 'prod',
      })
    }
  })

  it('lets the environment override the profile', () => {
    const { defaults } = loadProfile('product')
    expect(
      resolveDopplerLocation(defaults, { DOPPLER_PROJECT: 'other', DOPPLER_CONFIG: 'dev' }),
    ).toEqual({ project: 'other', config: 'dev' })
  })

  it('is undefined when neither profile nor environment says where', () => {
    expect(resolveDopplerLocation({ schema_version: '1' }, {})).toBeUndefined()
  })
})

describe('shouldReexecUnderDoppler', () => {
  it('does not wrap when the caller does not need credentials', () => {
    // Plain generation touches no secrets.
    expect(shouldReexecUnderDoppler({ required: false, satisfied: false }, {})).toBe(false)
  })

  it('wraps when credentials are needed and absent', () => {
    expect(shouldReexecUnderDoppler({ required: true, satisfied: false }, {})).toBe(true)
  })

  it('never wraps twice', () => {
    // The guard that stops a failed injection from looping forever: the child
    // sees the same empty environment that triggered the parent's re-exec.
    expect(
      shouldReexecUnderDoppler({ required: true, satisfied: false }, { KORAS_DOPPLER_REEXEC: '1' }),
    ).toBe(false)
  })

  it('does not wrap when the inputs are already exported by hand', () => {
    expect(shouldReexecUnderDoppler({ required: true, satisfied: true }, {})).toBe(false)
  })

  it('matches preflight against a fully populated environment', () => {
    // Guards the wiring: what the CLI passes as `satisfied` is this check.
    expect(preflightInputs(envWithInputs()).ok).toBe(true)
    expect(preflightInputs({}).ok).toBe(false)
  })
})

describe('reexecUnderDoppler', () => {
  it('passes project and config explicitly and re-runs this same argv', async () => {
    const calls: Array<{ command: string; args: string[]; env: NodeJS.ProcessEnv }> = []
    const spawner: Spawner = (command, args, env) => {
      calls.push({ command, args, env })
      return Promise.resolve(0)
    }

    const code = await reexecUnderDoppler(
      { project: 'koras-platform-bootstrap', config: 'prod' },
      ['/usr/bin/node', '/app/bin/create-koras-app.js', 'myapp', '--provision'],
      spawner,
      {},
    )

    expect(code).toBe(0)
    expect(calls[0].command).toBe('doppler')
    expect(calls[0].args).toEqual([
      'run',
      '--project',
      'koras-platform-bootstrap',
      '--config',
      'prod',
      '--',
      '/usr/bin/node',
      '/app/bin/create-koras-app.js',
      'myapp',
      '--provision',
    ])
    // A bare `doppler run` fails in a repo with no scope; the flags are required.
    expect(calls[0].args).toContain('--project')
    expect(calls[0].env.KORAS_DOPPLER_REEXEC).toBe('1')
  })

  it('propagates the child exit code', async () => {
    const spawner: Spawner = () => Promise.resolve(3)
    expect(
      await reexecUnderDoppler({ project: 'p', config: 'c' }, ['node', 'cli.js'], spawner, {}),
    ).toBe(3)
  })
})

describe('dopplerUnavailableMessage', () => {
  it('shows the wrapper the operator can run by hand', () => {
    expect(dopplerUnavailableMessage({ project: 'koras-platform-bootstrap', config: 'prod' }))
      .toContain('doppler run --project koras-platform-bootstrap --config prod --')
  })
})
