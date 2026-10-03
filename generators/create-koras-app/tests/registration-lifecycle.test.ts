import { describe, it, expect, beforeAll } from 'vitest'
import { execFileSync, spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { templatePath } from './template-path.js'

/**
 * Registration happens at generation *and* at every deployment.
 *
 * It used to happen once, at generation, from the outputs of the first
 * `terraform apply`, and nothing re-sent a reference afterwards. A service
 * added later, an environment provisioned later, a rotated ZITADEL project, or
 * a product generated before its Control Plane existed (R-001) all left the
 * registry holding the day the project was generated -- and reconciliation,
 * which compares the registry against reality, turned each of those into drift
 * with no explanation attached.
 *
 * `docs/REGISTRATION_LIFECYCLE.md` holds the reasoning. These hold the parts
 * that can be checked.
 */

const SCRIPT = 'local/scripts/register-with-control-plane.sh'

describe.each(['product', 'control-plane'] as const)('%s deploy-time registration', (profile) => {
  it('ships the re-registration script', () => {
    // From the shared layer, so it reaches both profiles -- which is exactly
    // why the script itself has to refuse on the Control Plane.
    expect(existsSync(templatePath(profile, ...SCRIPT.split('/')))).toBe(true)
  })

  it('calls it from deploy.yml, after the job that proves the API is serving', () => {
    const deploy = readFileSync(
      templatePath(profile, '.github', 'workflows', 'deploy.yml'),
      'utf8',
    )
    expect(deploy).toContain(SCRIPT)

    // `platform_api_base_url` is a reference the Control Plane calls back on.
    // Registering it before anything has answered on it registers a name rather
    // than a service.
    const verifyAt = deploy.indexOf('  verify:')
    const registerAt = deploy.indexOf('  register:')
    expect(verifyAt).toBeGreaterThan(-1)
    expect(registerAt).toBeGreaterThan(verifyAt)
    expect(deploy.slice(registerAt)).toMatch(/needs:\s*verify/)
  })

  it('leaves deploy.yml unrendered', () => {
    // The obvious guard for the job below would be a Handlebars conditional on
    // `registersAsProduct`, which the generator does expose. It is not
    // available: this file is dense with GitHub ${{ ... }} expressions and
    // Handlebars parses every one of them as a mustache, so rendering it turns
    // ${{ secrets.FLY_API_TOKEN }} into an empty string and leaves a workflow
    // that looks correct and authenticates as nobody. The guard is therefore at
    // runtime, in the script.
    expect(existsSync(templatePath(profile, '.github', 'workflows', 'deploy.yml') + '.hbs')).toBe(
      false,
    )
    const deploy = readFileSync(
      templatePath(profile, '.github', 'workflows', 'deploy.yml'),
      'utf8',
    )
    expect(deploy).toContain('secrets.DOPPLER_TOKEN')
    expect(deploy).not.toContain('{{registersAsProduct}}')
  })
})

/**
 * The script, run.
 *
 * Reading it would confirm the words are present; running it confirms the
 * behaviour, and the behaviour that matters most here is a refusal. `deploy.yml`
 * is shared by both profiles, so this script ships to the Control Plane too,
 * and a Control Plane that registers itself is a platform that believes it is
 * its own tenant.
 */
describe('register-with-control-plane.sh', () => {
  const ROOT = join(tmpdir(), `koras-register-${process.pid}-${Date.now()}`)
  const PROJECT = join(ROOT, 'project')
  const BIN = join(ROOT, 'bin')
  const PAYLOAD = join(ROOT, 'payload.json')
  /** The same path as bash sees it: a Windows separator is an escape inside a script. */
  const PAYLOAD_SH = PAYLOAD.replace(/\\/g, '/')

  /** Whether a POSIX shell and jq are available to run the script at all. */
  let runnable = false

  function write(path: string, content: string): void {
    mkdirSync(join(path, '..'), { recursive: true })
    writeFileSync(path, content)
  }

  function stubDoppler(values: Record<string, string>): void {
    // $3 is the secret name: `doppler secrets get <NAME> --plain ...`
    const cases = Object.entries(values)
      .map(([name, value]) => `  ${name}) echo "${value}" ;;`)
      .join('\n')
    write(join(BIN, 'doppler'), `#!/usr/bin/env bash\ncase "$3" in\n${cases}\n  *) exit 1 ;;\nesac\n`)
    chmodSync(join(BIN, 'doppler'), 0o755)
  }

  function setProfile(profile: string): void {
    write(
      join(PROJECT, '.koras', 'project.yaml'),
      [
        'schema_version: 1',
        'project:',
        '  name: shop',
        '  slug: shop',
        `  profile: ${profile}`,
        'generator:',
        '  name: create-koras-app',
        '  starter_version: 0.1.0',
        '  profile_version: 1.0.0',
        '',
      ].join('\n'),
    )
  }

  /**
   * Both streams, whatever the exit code. The script reports a tolerated
   * outcome on stderr and still exits 0 -- an unreachable Control Plane is the
   * case in point -- so a helper that reads stdout alone on success cannot see
   * the thing worth asserting.
   */
  function run(environment = 'prod'): Promise<{ status: number; output: string }> {
    // Awaited rather than spawnSync: the script takes tens of seconds, and a
    // worker blocked that long cannot answer vitest's reporter (R-031).
    return new Promise((resolve, reject) => {
      const child = spawn('bash', [join(PROJECT, SCRIPT)], {
        env: {
          ...process.env,
          PATH: `${BIN}:${process.env.PATH ?? ''}`,
          GITHUB_REPOSITORY: 'KORAS-Technologies/shop',
          ENVIRONMENT: environment,
        },
      })
      let output = ''
      child.stdout.setEncoding('utf8').on('data', (chunk: string) => (output += chunk))
      child.stderr.setEncoding('utf8').on('data', (chunk: string) => (output += chunk))
      child.on('error', reject)
      child.on('close', (status) => resolve({ status: status ?? 1, output }))
    })
  }

  beforeAll(() => {
    try {
      execFileSync('bash', ['-c', 'command -v jq'], { stdio: 'ignore' })
      runnable = true
    } catch {
      runnable = false
      return
    }

    mkdirSync(BIN, { recursive: true })
    write(
      join(PROJECT, SCRIPT),
      readFileSync(templatePath('product', ...SCRIPT.split('/')), 'utf8'),
    )
    // Its sibling, which it calls to decide what is deployed here. The script
    // stopped carrying its own copy of that rule on 2026-10-03 (the copy would
    // have registered a service in environments it is not deployed to), so a
    // project that has the one has the other: both are `local/scripts`.
    write(
      join(PROJECT, 'local', 'scripts', 'service-descriptor.sh'),
      readFileSync(templatePath('product', 'local', 'scripts', 'service-descriptor.sh'), 'utf8'),
    )
    write(
      join(PROJECT, 'infrastructure', 'terraform', 'terraform.tfvars'),
      'primary_domain = "shop.example.com"\n',
    )
    for (const service of ['api', 'worker']) {
      write(join(PROJECT, 'services', service, 'Dockerfile'), 'FROM scratch\n')
      write(join(PROJECT, 'services', service, 'fly.toml'), 'app = "x"\n')
    }
    stubCurl('ok')
  })

  /**
   * `ok` captures the request rather than sending it and reports 201.
   * `unreachable` behaves the way the real curl does when it cannot connect: it
   * prints `000` for `%{http_code}` *and* exits non-zero. Both halves matter --
   * reading them as one value is how the tolerated outcome became a failure.
   */
  function stubCurl(mode: 'ok' | 'unreachable'): void {
    const body =
      mode === 'ok'
        ? [
            `  [ "\${args[$i]}" = "--data-binary" ] && printf '%s' "\${args[$((i+1))]}" > ${PAYLOAD_SH}`,
            'done',
            `echo '{"id":"uuid","status":"registered"}' > "$out"`,
            "printf '201'",
          ]
        : ['done', ': > "$out"', 'echo "curl: (7) Failed to connect" >&2', "printf '000'", 'exit 7']
    write(
      join(BIN, 'curl'),
      [
        '#!/usr/bin/env bash',
        'out=""; args=("$@")',
        'for i in "${!args[@]}"; do',
        '  [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"',
        ...body,
        '',
      ].join('\n'),
    )
    chmodSync(join(BIN, 'curl'), 0o755)
  }

  it('refuses to register the Control Plane, and says nothing was sent', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('control-plane')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
    })

    const { status, output } = await run()

    // Not a failure: the Control Plane's pipeline is correct and should stay
    // green. It simply has nothing to register.
    expect(status).toBe(0)
    expect(output).toContain('control-plane')
    // The load-bearing assertion. Even with a Control Plane configured and a
    // token in hand, no request left.
    expect(existsSync(PAYLOAD)).toBe(false)
  })

  it('refuses a profile it does not recognise rather than passing silently', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('something-else')
    stubDoppler({ KORAS_CONTROL_PLANE_URL: 'https://cp.example.com' })

    expect((await run()).status).toBe(2)
    expect(existsSync(PAYLOAD)).toBe(false)
  })

  it('treats an unconfigured Control Plane as the bootstrap order, not a failure', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({})

    // R-001: the first product in a new estate is provisioned before the
    // registry it would register with exists.
    const { status, output } = await run()
    expect(status).toBe(0)
    expect(output).toContain('bootstrap order')
    expect(existsSync(PAYLOAD)).toBe(false)
  })

  it('fails on a Control Plane named with nothing to authorise the call', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({ KORAS_CONTROL_PLANE_URL: 'https://cp.example.com' })

    // A misconfiguration reported as nothing-to-do is one nobody fixes.
    expect((await run()).status).toBe(1)
    expect(existsSync(PAYLOAD)).toBe(false)
  })

  it('refuses to send a bearer token over plaintext http', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'http://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
    })

    expect((await run()).status).toBe(1)
    expect(existsSync(PAYLOAD)).toBe(false)
  })

  it('builds a payload the Control Plane schema accepts', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
      ZITADEL_PROJECT_ID: '123456789',
      ZITADEL_CLIENT_ID: 'client-abc',
    })

    expect((await run()).status).toBe(0)
    const payload = JSON.parse(readFileSync(PAYLOAD, 'utf8'))

    // Field-for-field against `ProductRegistrationRequest`, which sets
    // extra="forbid" -- an invented name here is a 422 rather than something
    // quietly ignored.
    expect(Object.keys(payload).sort()).toEqual([
      'code',
      'environments',
      'name',
      'primary_domain',
      'profile',
      'profile_version',
      'repository',
      'slug',
      'starter_version',
    ])
    expect(payload.profile).toBe('product')

    // One environment, not four. Safe only because the Control Plane upserts
    // environments and never prunes them, so the other three are untouched --
    // read out of its repository layer rather than assumed.
    expect(Object.keys(payload.environments)).toEqual(['prod'])

    const spec = payload.environments.prod
    // Services *are* pruned within an environment, so this list has to be what
    // is deployed rather than what was generated.
    expect(spec.services).toEqual(['api', 'worker'])
    expect(spec.infrastructure.fly_apps).toEqual({
      api: 'shop-api-prod',
      worker: 'shop-worker-prod',
    })
    expect(spec.infrastructure.platform_api_base_url).toBe('https://shop-api-prod.fly.dev')
    expect(spec.infrastructure.doppler_config).toBe('prod')
    // The one reference generation-time registration cannot carry: its
    // Terraform output is marked sensitive, and un-marking it would be the
    // trade the contract exists to refuse.
    expect(spec.infrastructure.zitadel_client_id).toBe('client-abc')
  })

  it('registers a service only in the environments its descriptor allows', async () => {
    if (!runnable) return
    const yq = spawnSync('yq', ['--version'], { encoding: 'utf8' })
    if (!(yq.status === 0 && /mikefarah/.test(yq.stdout))) return
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
      ZITADEL_PROJECT_ID: '123456789',
      ZITADEL_CLIENT_ID: 'client-abc',
    })
    // The scanner: a deployable service whose descriptor limits it to dev.
    write(join(PROJECT, 'services', 'clamd', 'Dockerfile'), 'FROM scratch\n')
    write(join(PROJECT, 'services', 'clamd', 'fly.toml'), 'app = "x"\n')
    write(
      join(PROJECT, 'services', 'clamd', 'service.yaml'),
      'schema_version: 1\nenvironments:\n  - dev\nsecrets:\n  policy: none\nnetwork: private\n',
    )
    try {
      rmSync(PAYLOAD, { force: true })
      expect((await run('dev')).status).toBe(0)
      expect(JSON.parse(readFileSync(PAYLOAD, 'utf8')).environments.dev.services).toEqual([
        'api',
        'clamd',
        'worker',
      ])

      // The registry prunes by this list. clamd is not deployed to prod, so
      // naming it there would have reconciliation report drift nobody caused.
      rmSync(PAYLOAD, { force: true })
      expect((await run('prod')).status).toBe(0)
      expect(JSON.parse(readFileSync(PAYLOAD, 'utf8')).environments.prod.services).toEqual(['api', 'worker'])
    } finally {
      rmSync(join(PROJECT, 'services', 'clamd'), { recursive: true, force: true })
    }
  })

  it('carries the three columns a missing value would blank', () => {
    if (!runnable) return
    // The product row is overwritten wholesale from the request, so an omitted
    // column is written as NULL. These three have no other source.
    const payload = JSON.parse(readFileSync(PAYLOAD, 'utf8'))
    expect(payload.primary_domain).toBe('shop.example.com')
    expect(payload.starter_version).toBe('0.1.0')
    expect(payload.profile_version).toBe('1.0.0')
  })

  it('sends nothing at all when one of those three cannot be read', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
    })
    const tfvars = join(PROJECT, 'infrastructure', 'terraform', 'terraform.tfvars')
    const saved = readFileSync(tfvars, 'utf8')
    writeFileSync(tfvars, '# no primary_domain here\n')

    try {
      // A registration that quietly empties a column is worse than one that did
      // not run.
      expect((await run()).status).toBe(1)
      expect(existsSync(PAYLOAD)).toBe(false)
    } finally {
      writeFileSync(tfvars, saved)
    }
  })

  it('does not fail a green deployment because the registry was down', async () => {
    if (!runnable) return
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
      ZITADEL_PROJECT_ID: '1',
      ZITADEL_CLIENT_ID: 'c',
    })
    stubCurl('unreachable')

    try {
      // The deployment has already succeeded by the time this job runs, and the
      // next deployment re-sends the same request. Failing here would train
      // people to ignore the job.
      //
      // This was briefly wrong in a way worth keeping a test for: reading the
      // status as `$(curl ... || echo 000)` appends a second value to what curl
      // already printed, so the status matched no case and the tolerated
      // outcome became a hard failure.
      const { status, output } = await run()
      expect(status).toBe(0)
      expect(output).toContain('could not be reached')
    } finally {
      stubCurl('ok')
    }
  })

  it('carries no field whose name looks like a credential', async () => {
    if (!runnable) return
    rmSync(PAYLOAD, { force: true })
    setProfile('product')
    stubDoppler({
      KORAS_CONTROL_PLANE_URL: 'https://cp.example.com',
      KORAS_CONTROL_PLANE_TOKEN: 'tok',
      ZITADEL_PROJECT_ID: '1',
      ZITADEL_CLIENT_ID: 'c',
    })
    expect((await run()).status).toBe(0)

    const raw = readFileSync(PAYLOAD, 'utf8')
    const names = [...raw.matchAll(/"([^"]+)"\s*:/g)].map((m) => m[1])
    for (const name of names) {
      expect(name).not.toMatch(/secret|token|password|credential|private_key|api_key|access_key/i)
    }
    // And the token, which the script does hold, is not in the body either.
    expect(raw).not.toContain('tok')
  })
})
