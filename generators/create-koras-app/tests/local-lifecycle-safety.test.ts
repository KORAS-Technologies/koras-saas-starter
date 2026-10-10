import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join, delimiter } from 'node:path'
import { spawnSync } from 'node:child_process'
import { createServer, type Server } from 'node:net'
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
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

/**
 * A generated project's local stack cannot lose its data by accident.
 *
 * `make reset` and `pnpm stack:reset` used to be a bare `docker compose down -v`:
 * no confirmation, no check of which daemon docker pointed at, and -- because
 * the compose project name is fixed -- a reset in any git worktree deleted the
 * main checkout's volumes, ZITADEL instance included. Docoris found the gap
 * (its D-018) and guarded its own `reset.sh`, but nothing called it.
 *
 * Every script here runs against a stub `docker` (and stub `curl`) placed first
 * on PATH, in a throwaway root. Nothing in this file talks to a Docker daemon.
 */

const OUT = join(tmpdir(), `koras-lifecycle-${process.pid}-${Date.now()}`)
const bash = spawnSync('bash', ['--version']).status === 0

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

async function generate(profile: ProfileName, slug: string) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, {})
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  const root = join(OUT, slug)
  return { root, fileList, read: (rel: string) => readFileSync(join(root, rel), 'utf8') }
}

interface Stub {
  contextShow?: string | null // null: `docker context show` fails
  contextHost?: string
  volumes?: string[] | null // null: `docker volume ls` fails
  published?: string
}

/** A fake `docker` and `curl` that record every invocation and touch nothing. */
function stubBin(dir: string, stub: Stub = {}): { bin: string; calls: string } {
  const bin = join(dir, 'stub-bin')
  mkdirSync(bin, { recursive: true })
  const calls = join(dir, 'calls.log')
  const contextShow = stub.contextShow === null ? 'exit 1' : `echo ${stub.contextShow ?? 'default'}`
  const volumes =
    stub.volumes === null ? 'exit 1' : `printf '%s\\n' ${(stub.volumes ?? []).join(' ')}`
  const docker = `#!/usr/bin/env bash
echo "docker $*" >> '${calls.replace(/\\/g, '/')}'
case "$1 $2" in
  "context show") ${contextShow} ;;
  "context inspect") echo '${stub.contextHost ?? 'unix:///var/run/docker.sock'}' ;;
  "volume ls") ${volumes} ;;
  "ps --filter") echo '${stub.published ?? ''}' ;;
esac
exit 0
`
  writeFileSync(join(bin, 'docker'), docker)
  writeFileSync(
    join(bin, 'curl'),
    `#!/usr/bin/env bash\necho "curl $*" >> '${calls.replace(/\\/g, '/')}'\nexit 7\n`,
  )
  chmodSync(join(bin, 'docker'), 0o755)
  chmodSync(join(bin, 'curl'), 0o755)
  return { bin, calls }
}

function run(
  script: string,
  args: string[],
  cwd: string,
  bin: string,
  env: NodeJS.ProcessEnv = {},
) {
  return spawnSync('bash', [script, ...args], {
    cwd,
    encoding: 'utf8',
    // stdin is a pipe, never a TTY: the unattended case.
    input: '',
    env: { ...process.env, DOCKER_HOST: '', ...env, PATH: `${bin}${delimiter}${process.env.PATH}` },
  })
}

function callsOf(calls: string): string {
  return existsSync(calls) ? readFileSync(calls, 'utf8') : ''
}

// ── wiring ───────────────────────────────────────────────────────────────────

describe.each(['product', 'control-plane'] as const)('%s: destructive entry points', (profile) => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate(profile, `${profile}-wiring`)
  })

  it('routes make reset through the guarded script', () => {
    const makefile = gen.read('Makefile')
    const target = /^reset:.*\n((?:\t.*\n)+)/m.exec(makefile)?.[1] ?? ''
    expect(target.trim()).toBe('bash ./local/scripts/reset.sh')
  })

  it('routes pnpm stack:reset through the guarded script', () => {
    const scripts = JSON.parse(gen.read('package.json')).scripts as Record<string, string>
    expect(scripts['stack:reset']).toBe('bash local/scripts/reset.sh')
  })

  it('deletes volumes nowhere but reset.sh', () => {
    // The guard is only a guard if it is the one door. Any other file that can
    // run `down -v` is a way around it.
    const destructive =
      /down\s+(?:[^\n#]*\s)?(?:-v\b|--volumes\b)|volume\s+(?:rm|prune)\b|system\s+prune\b/
    // Comment lines are skipped: the Makefile's own warning names the command.
    // The reset suite is exempt by exact path: it names the command in order to
    // assert that the stub docker did, or did not, receive it.
    const exempt = new Set(['local/scripts/reset.sh', 'tests/security/test_reset_script_safety.py'])
    const offenders = gen.fileList.filter((f) => {
      if (exempt.has(f) || /\.(png|ico|woff2?|zip)$/.test(f)) return false
      return gen
        .read(f)
        .split('\n')
        .some((line) => !/^\s*(#|\/\/)/.test(line) && destructive.test(line))
    })
    expect(offenders).toEqual([])
  })

  it('offers stop and down, both of which keep volumes', () => {
    // Through stack.mjs since Phase 4.3: compose cannot load the file without
    // its values, and its passthrough refuses `down -v` (asserted in
    // local-zitadel-secure.test.ts).
    const makefile = gen.read('Makefile')
    expect(makefile).toMatch(/^stop:.*\n\tnode \.\/local\/scripts\/stack\.mjs compose stop$/m)
    expect(makefile).toMatch(/^down:.*\n\tnode \.\/local\/scripts\/stack\.mjs compose down$/m)
    const scripts = JSON.parse(gen.read('package.json')).scripts as Record<string, string>
    expect(scripts['stack:stop']).toBe('node local/scripts/stack.mjs compose stop')
  })

  it('runs the read-only preflight before make dev', () => {
    const dev = /^dev:.*\n((?:\t.*\n)+)/m.exec(gen.read('Makefile'))?.[1] ?? ''
    expect(dev.split('\n')[0].trim()).toBe('bash ./local/scripts/preflight.sh')
  })
})

// ── reset.sh behaviour ───────────────────────────────────────────────────────

describe.skipIf(!bash)('reset.sh refuses unless local, confirmed and scoped', () => {
  let script: string
  let n = 0

  beforeAll(async () => {
    const gen = await generate('product', 'reset-behaviour')
    script = join(gen.root, 'local', 'scripts', 'reset.sh')
  })

  /** A throwaway project root holding only what reset.sh reads. */
  function fixture(envLocal?: string): string {
    const root = join(OUT, `reset-fixture-${n++}`)
    mkdirSync(join(root, 'local', 'scripts'), { recursive: true })
    writeFileSync(join(root, 'local', 'docker-compose.yml'), 'name: fixture-app\nservices: {}\n')
    writeFileSync(
      join(root, 'local', 'scripts', 'bootstrap.sh'),
      `#!/usr/bin/env bash\ntouch '${join(root, 'bootstrap-ran').replace(/\\/g, '/')}'\n`,
    )
    copyFileSync(script, join(root, 'local', 'scripts', 'reset.sh'))
    if (envLocal !== undefined) writeFileSync(join(root, '.env.local'), envLocal)
    return root
  }

  const LOCAL_ENV = [
    'DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres',
    'ZITADEL_DOMAIN=http://localhost:8080',
    'SMTP_HOST=localhost',
    'CORS_ORIGINS=["https://app.localhost","https://admin.localhost"]',
    'SESSION_SECRET=kept-across-reset',
    '',
  ].join('\n')

  it('refuses an unattended run without --force, and never calls compose', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root, { volumes: ['fixture-app_supabase-db'] })
    const r = run(join(root, 'local/scripts/reset.sh'), [], root, bin)
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/no TTY/)
    expect(callsOf(calls)).not.toMatch(/docker compose/)
    expect(existsSync(join(root, '.env.local'))).toBe(true)
  })

  it('with --force, lists the volumes, tears down, and keeps .env.local aside', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root, {
      volumes: ['fixture-app_supabase-db', 'fixture-app_redis-data'],
    })
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status, r.stderr).toBe(0)
    expect(r.stdout).toContain('fixture-app_supabase-db')
    const log = callsOf(calls)
    expect(log).toMatch(/volume ls --filter label=com\.docker\.compose\.project=fixture-app/)
    expect(log).toMatch(/compose -f .*docker-compose\.yml down --volumes --remove-orphans/)
    // Moved, not deleted: it can hold values nothing regenerates.
    const kept = readdirSync(root).filter((f) => f.startsWith('.env.local.pre-reset-'))
    expect(kept).toHaveLength(1)
    expect(readFileSync(join(root, kept[0]), 'utf8')).toContain('SESSION_SECRET=kept-across-reset')
    expect(existsSync(join(root, 'bootstrap-ran'))).toBe(true)
  })

  it.each([
    [
      'DATABASE_URL=postgresql://postgres:pw@db.example.supabase.co:5432/postgres',
      'a deployed database',
    ],
    ['ZITADEL_DOMAIN=https://localhost.attacker.example', 'a lookalike of localhost'],
    ['REDIS_URL=redis://127.0.0.1.attacker.example:6379', 'a lookalike of loopback'],
    [
      'CORS_ORIGINS=["https://app.localhost","https://app.example.com"]',
      'one remote origin in a list',
    ],
    ['KORAS_CONTROL_PLANE_URL=https://cp.example.com', 'a setting no hand-kept list named'],
  ])('refuses when .env.local points at %s (%s)', (line) => {
    const root = fixture(`${LOCAL_ENV}${line}\n`)
    const { bin, calls } = stubBin(root)
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/does not look local/)
    expect(callsOf(calls)).not.toMatch(/docker compose|docker volume ls/)
  })

  it('refuses a remote DOCKER_HOST', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root)
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin, {
      DOCKER_HOST: 'tcp://build-server.example:2376',
    })
    expect(r.status).toBe(1)
    expect(callsOf(calls)).not.toMatch(/docker compose/)
  })

  it('refuses when the docker context cannot be determined', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root, { contextShow: null })
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/docker context/)
    expect(callsOf(calls)).not.toMatch(/docker compose/)
  })

  it('refuses a non-default context that points at a remote daemon', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root, {
      contextShow: 'shared',
      contextHost: 'ssh://ops@build.example',
    })
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status).toBe(1)
    expect(callsOf(calls)).not.toMatch(/docker compose/)
  })

  it("accepts Docker Desktop's own context, which is local but not named default", () => {
    const root = fixture(LOCAL_ENV)
    const { bin } = stubBin(root, {
      contextShow: 'desktop-linux',
      contextHost: 'npipe:////./pipe/dockerDesktopLinuxEngine',
    })
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status, r.stderr).toBe(0)
  })

  it('refuses when it cannot list what it would delete', () => {
    const root = fixture(LOCAL_ENV)
    const { bin, calls } = stubBin(root, { volumes: null })
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/could not list the volumes/)
    expect(callsOf(calls)).not.toMatch(/docker compose/)
  })

  it('refuses a compose file without a project name', () => {
    const root = fixture(LOCAL_ENV)
    writeFileSync(join(root, 'local', 'docker-compose.yml'), 'services: {}\n')
    const { bin, calls } = stubBin(root)
    const r = run(join(root, 'local/scripts/reset.sh'), ['--force'], root, bin)
    expect(r.status).toBe(1)
    expect(callsOf(calls)).toBe('')
  })

  it('refuses in a linked git worktree, even with --force', () => {
    // Worktrees share the compose project name, so this reset would delete the
    // main checkout's volumes.
    const main = fixture(LOCAL_ENV)
    const git = (cwd: string, ...args: string[]) => {
      const r = spawnSync('git', args, { cwd, encoding: 'utf8' })
      if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`)
    }
    git(main, 'init', '-q')
    git(main, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', 'add', '-A')
    git(
      main,
      '-c',
      'user.email=t@example.invalid',
      '-c',
      'user.name=t',
      'commit',
      '-q',
      '-m',
      'fixture',
    )
    const wt = join(OUT, `reset-worktree-${n++}`)
    git(main, 'worktree', 'add', '-q', wt)
    const { bin, calls } = stubBin(wt)
    const r = run(join(wt, 'local/scripts/reset.sh'), ['--force'], wt, bin)
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/linked git worktree/)
    expect(callsOf(calls)).toBe('')

    // ...while the main checkout itself is still allowed.
    const ok = stubBin(main)
    expect(run(join(main, 'local/scripts/reset.sh'), ['--force'], main, ok.bin).status).toBe(0)
  })
})

// ── preflight.sh behaviour ───────────────────────────────────────────────────

describe.skipIf(!bash)('preflight.sh warns and changes nothing', () => {
  let gen: Awaited<ReturnType<typeof generate>>
  let server: Server
  let busyPort = 0

  beforeAll(async () => {
    gen = await generate('product', 'preflight-behaviour')
    server = createServer()
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const address = server.address()
    busyPort = typeof address === 'object' && address ? address.port : 0
  })

  afterAll(() => {
    server?.close()
  })

  function snapshot(root: string): string[] {
    const out: string[] = []
    const walk = (dir: string) => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (e.name === 'stub-bin' || e.name === 'calls.log') continue
        const p = join(dir, e.name)
        if (e.isDirectory()) walk(p)
        else out.push(`${p}:${readFileSync(p).length}`)
      }
    }
    walk(root)
    return out.sort()
  }

  it('reports missing configuration and an unrecorded instance, exits 0, writes nothing', () => {
    const { bin, calls } = stubBin(gen.root)
    const before = snapshot(gen.root)
    const home = join(OUT, 'preflight-koras-home')
    const r = run(join(gen.root, 'local/scripts/preflight.sh'), [], gen.root, bin, {
      KORAS_HOME: home,
    })
    expect(r.status, r.stderr).toBe(0)
    expect(r.stdout).toMatch(/WARN\s+local\/\.env is missing/)
    expect(r.stdout).toMatch(/WARN\s+\.env\.local is missing/)
    expect(r.stdout).toMatch(/WARN\s+no local ZITADEL instance is recorded/)
    // The generated base file is clean, so nothing here is an error.
    expect(r.stdout).not.toMatch(/ERROR/)
    expect(existsSync(home)).toBe(false)
    expect(snapshot(gen.root)).toEqual(before)
    // Read-only against docker too: at most `docker ps`.
    expect(callsOf(calls)).not.toMatch(/docker (?:compose|volume|rm|stop|start|run)/)
  })

  it('fails under --strict when there is any warning', () => {
    const { bin } = stubBin(gen.root)
    expect(
      run(join(gen.root, 'local/scripts/preflight.sh'), ['--strict'], gen.root, bin).status,
    ).toBe(1)
  })

  it('names a port another process holds, and not one this stack holds', () => {
    const root = join(OUT, 'preflight-ports')
    mkdirSync(join(root, 'local', 'scripts'), { recursive: true })
    copyFileSync(
      join(gen.root, 'local/scripts/preflight.sh'),
      join(root, 'local/scripts/preflight.sh'),
    )
    copyFileSync(join(gen.root, 'local/docker-compose.yml'), join(root, 'local/docker-compose.yml'))
    writeFileSync(
      join(root, 'local', '.env'),
      `KORAS_PORT_ZITADEL=${busyPort}\nKORAS_PORT_REDIS=1\n`,
    )

    const foreign = stubBin(join(root, 'a'))
    const r = run(join(root, 'local/scripts/preflight.sh'), [], root, foreign.bin)
    expect(r.stdout).toContain(
      `KORAS_PORT_ZITADEL=${busyPort} is already in use by another process`,
    )
    expect(r.stdout).not.toContain('KORAS_PORT_REDIS')

    const own = stubBin(join(root, 'b'), { published: `0.0.0.0:${busyPort}->8080/tcp` })
    const mine = run(join(root, 'local/scripts/preflight.sh'), [], root, own.bin)
    expect(mine.stdout).toContain(
      `KORAS_PORT_ZITADEL=${busyPort} (held by this stack's containers)`,
    )
  })

  it('reports .env.local placeholders by name, never by value', () => {
    const root = join(OUT, 'preflight-env')
    mkdirSync(join(root, 'local', 'scripts'), { recursive: true })
    copyFileSync(
      join(gen.root, 'local/scripts/preflight.sh'),
      join(root, 'local/scripts/preflight.sh'),
    )
    writeFileSync(
      join(root, '.env.local'),
      'ZITADEL_CLIENT_SECRET=<from-zitadel-console>\nSESSION_SECRET=short-but-secret-value\nREDIS_URL=redis://localhost:6379\n',
    )
    const { bin } = stubBin(root)
    const r = run(join(root, 'local/scripts/preflight.sh'), [], root, bin)
    expect(r.stdout).toMatch(/template placeholders: ZITADEL_CLIENT_SECRET/)
    expect(r.stdout).toMatch(/SESSION_SECRET in \.env\.local is shorter than 32 characters/)
    expect(r.stdout).not.toContain('short-but-secret-value')
  })
})

// ── ZITADEL URL ──────────────────────────────────────────────────────────────

describe.each(['product', 'control-plane'] as const)('%s: ZITADEL URL is explicit', (profile) => {
  let gen: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    gen = await generate(profile, `${profile}-zitadel-url`)
  })

  it('has no implicit port default in init.sh or provision.py', () => {
    // http://localhost:8083 is the Control Plane's preferred ZITADEL port. As a
    // default, a product run by hand provisioned itself into the Control
    // Plane's instance.
    // `${ZITADEL_URL:-}` (empty) is the emptiness check; anything after `:-` is a default.
    expect(gen.read('local/zitadel/init.sh')).not.toMatch(/ZITADEL_URL:-[^}]/)
    expect(gen.read('local/zitadel/provision.py')).not.toMatch(
      /environ\.get\("ZITADEL_URL",\s*"http/,
    )
  })

  it.skipIf(!bash)('init.sh refuses without ZITADEL_URL and contacts nothing', () => {
    const { bin, calls } = stubBin(join(gen.root, '.stub'))
    const r = run(join(gen.root, 'local/zitadel/init.sh'), [], gen.root, bin, { ZITADEL_URL: '' })
    expect(r.status).toBe(1)
    expect(r.stderr).toMatch(/ZITADEL_URL is not set/)
    expect(callsOf(calls)).toBe('')
  })

  it.skipIf(!bash)("init.sh names this project's resolved port when it knows it", () => {
    writeFileSync(join(gen.root, 'local', '.env'), 'KORAS_PORT_ZITADEL=8099\n')
    const { bin } = stubBin(join(gen.root, '.stub2'))
    const r = run(join(gen.root, 'local/zitadel/init.sh'), [], gen.root, bin, { ZITADEL_URL: '' })
    expect(r.status).toBe(1)
    expect(r.stderr).toContain('ZITADEL_URL=http://localhost:8099 bash local/zitadel/init.sh')
    rmSync(join(gen.root, 'local', '.env'))
  })

  it('bootstrap resolves ports first, and stack.mjs passes the recorded issuer', () => {
    // Since Phase 4.3 bootstrap hands ZITADEL to stack.mjs, which runs
    // provision.py with the issuer the instance was created on -- read from
    // its state, never from a default.
    const bootstrap = gen.read('local/scripts/bootstrap.sh')
    const ports = bootstrap.indexOf('bash "$ROOT/local/scripts/ports.sh"')
    const stack = bootstrap.indexOf('node "$ROOT/local/scripts/stack.mjs" bootstrap')
    expect(ports).toBeGreaterThan(-1)
    expect(stack).toBeGreaterThan(ports)
    expect(gen.read('local/scripts/stack.mjs')).toMatch(/ZITADEL_URL: state\.issuer/)
  })
})
