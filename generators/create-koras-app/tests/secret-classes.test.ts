import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, chmodSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { load as parseYaml } from 'js-yaml'
import { templatePath } from './template-path.js'

/** A workflow's job graph, as much of it as these assertions read. */
interface Workflow {
  jobs: Record<string, { needs?: string | string[]; steps: Array<{ name?: string; run?: string }> }>
}

function load(path: string): Workflow {
  return parseYaml(readFileSync(path, 'utf8')) as Workflow
}

/**
 * What a settings class means, and that the checker enforces it.
 *
 * PLAT-DEF-014. `secrets.manifest` classes every setting, and `local` was
 * documented as "never in Doppler" while nothing checked it. Three links made
 * that load-bearing rather than tidy: `next build` *defaults* `NODE_ENV`
 * rather than forcing it, `deploy.yml` pushes every Doppler key into the
 * provider's production environment, and `doppler-check.sh` only ever asked
 * whether required names were *present*. So one `doppler secrets set
 * NODE_ENV=development` reached a production bundle, and the only signal was a
 * warning in a log nobody reads.
 *
 * **The class had to be fixed before the rule could be.** `local` meant two
 * things: genuinely-never-deployed for the local Docker stack, and, in the
 * Control Plane manifest, four SMTP settings the deployed Control Plane
 * actually reads from Doppler and which are present in all four of its configs
 * today. Enforcing "local means forbidden" against that would have failed every
 * Control Plane deployment. They are `optional` now -- the class that already
 * meant this, and what the product manifest had always said about the same four
 * names.
 *
 * The shell is executed rather than pattern-matched, in the shape
 * `app-role-url.test.ts` established: the defect being guarded is a missing
 * comparison, and asserting that the source contains a comparison is asserting
 * the thing that was already wrong. `doppler` is stubbed, so this needs no
 * credentials and reads no value -- which is also the property under test.
 */

const PROFILES = ['product', 'control-plane'] as const
type Profile = (typeof PROFILES)[number]

/** Every non-comment `NAME CLASS [SOURCE] [TYPE]` row of a profile's manifest. */
interface Entry {
  name: string
  klass: string
}

/**
 * The manifest as a generated project receives it.
 *
 * The capability conditionals are removed *inline* rather than by dropping the
 * lines carrying them, because the template glues them to entries --
 * `{{/if}}DATABASE_URL` is one line and one setting. Dropping the line loses a
 * required name, which is how the first version of this harness built a fixture
 * the checker then failed on four Handlebars tags it had read as settings.
 * Stripping the expressions is what generation does.
 */
function rendered(profile: Profile): string {
  return readFileSync(templatePath(profile, 'local/config/secrets.manifest.hbs'), 'utf8').replace(
    /\{\{[^}]*\}\}/g,
    '',
  )
}

function manifest(profile: Profile): Entry[] {
  const entries: Entry[] = []
  for (const line of rendered(profile).split('\n')) {
    const trimmed = line.trim()
    if (trimmed === '' || trimmed.startsWith('#')) continue
    const [name, klass] = trimmed.split(/\s+/)
    if (name === undefined || klass === undefined) continue
    if (!/^[A-Z][A-Z0-9_]*$/.test(name)) continue
    entries.push({ name, klass })
  }
  return entries
}

/** The four classes the manifests use. A fifth would be a schema change. */
const CLASSES = ['local', 'derived', 'supplied', 'optional']

describe('the settings manifest classifies every setting deliberately', () => {
  for (const profile of PROFILES) {
    describe(profile, () => {
      const entries = manifest(profile)

      it('finds settings to check', () => {
        // A parser that matched nothing would make every assertion below pass
        // over an empty list.
        expect(entries.length).toBeGreaterThan(20)
      })

      it('uses only the classes the checker understands', () => {
        const unknown = entries.filter((entry) => !CLASSES.includes(entry.klass))
        expect(unknown.map((entry) => `${entry.name} ${entry.klass}`)).toEqual([])
      })

      it('names each setting once', () => {
        const seen = new Map<string, number>()
        for (const entry of entries) seen.set(entry.name, (seen.get(entry.name) ?? 0) + 1)
        expect([...seen].filter(([, count]) => count > 1).map(([name]) => name)).toEqual([])
      })

      it('forbids NODE_ENV from Doppler', () => {
        // The central PLAT-DEF-014 criterion, and it belongs in both profiles:
        // a Control Plane built in development mode is the same defect.
        expect(entries.find((entry) => entry.name === 'NODE_ENV')?.klass).toBe('local')
      })
    })
  }

  it('keeps the local class for settings a deployed environment must not hold', () => {
    const local = manifest('product')
      .filter((entry) => entry.klass === 'local')
      .map((entry) => entry.name)
      .sort()
    expect(local).toEqual([
      'GRAFANA_PASSWORD',
      'MINIO_ROOT_PASSWORD',
      'MINIO_ROOT_USER',
      'NODE_ENV',
      'ZITADEL_MASTERKEY',
    ])
  })

  it('does not forbid the Control Plane the mail settings it reads', () => {
    // These were `local` until 2026-09-20. The deployed Control Plane reads
    // them -- `services/worker/koras_worker/settings.py` declares them and its
    // own comment says they should become required once they are in Doppler
    // for every environment -- and all four of its configs hold them today.
    const entries = manifest('control-plane')
    for (const name of ['SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURE', 'SMTP_FROM']) {
      expect(entries.find((entry) => entry.name === name)?.klass, name).toBe('optional')
    }
    // And the product says the same thing about the same names, which is the
    // agreement whose absence was the finding.
    const product = manifest('product')
    for (const name of ['SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURE', 'SMTP_FROM']) {
      expect(product.find((entry) => entry.name === name)?.klass, name).toBe('optional')
    }
  })

  it('parses a row that carries a SOURCE and a TYPE', () => {
    // `SMTP_PORT optional - int` is the four-column form: the SOURCE column is
    // positional and holds `-` when a typed setting has no source. A parser
    // that took the last field as the class would read `int` here.
    expect(manifest('control-plane').find((entry) => entry.name === 'SMTP_PORT')?.klass).toBe(
      'optional',
    )
    expect(manifest('product').find((entry) => entry.name === 'ENVIRONMENT')?.klass).toBe('derived')
  })
})

// ── the checker itself, executed ─────────────────────────────────────────────

/**
 * A project tree just complete enough for `doppler-check.sh` to run, with
 * `doppler` stubbed to answer a fixed name list.
 *
 * The stub is the point: the script must never ask for a value, so the stub
 * answers `--only-names` and *fails loudly* on anything else. A future
 * maintainer who "improves" the check by switching to `doppler secrets
 * download` gets a red test rather than a validator that quietly holds secrets.
 */
function runCheck(options: {
  profile: Profile
  present: string[]
  manifestText?: string
}): { status: number; stdout: string; stderr: string } {
  const root = mkdtempSync(join(tmpdir(), 'koras-doppler-'))
  try {
    mkdirSync(join(root, 'local', 'scripts'), { recursive: true })
    mkdirSync(join(root, 'local', 'config'), { recursive: true })
    mkdirSync(join(root, 'stub'), { recursive: true })

    const script = readFileSync(
      join(templatePath('product', 'package.json.hbs'), '..', '..', '..', '_shared', 'template', 'local', 'scripts', 'doppler-check.sh.hbs'),
      'utf8',
    )
      .split('{{projectSlug}}')
      .join('fixture')
      .split('{{profile}}')
      .join(options.profile)
    writeFileSync(join(root, 'local', 'scripts', 'doppler-check.sh'), script)

    const manifestText = options.manifestText ?? rendered(options.profile)
    writeFileSync(join(root, 'local', 'config', 'secrets.manifest'), manifestText)

    // The contract file the script cross-checks against. Every manifest name,
    // so the "classified but not contracted" check passes and the run reaches
    // the part under test.
    const names = manifestText
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== '' && !line.startsWith('#'))
      .map((line) => line.split(/\s+/)[0])
      .filter((name): name is string => name !== undefined && /^[A-Z][A-Z0-9_]*$/.test(name))
    writeFileSync(
      join(root, 'local', 'config', '.env.local.example'),
      names.map((name) => `${name}=x`).join('\n') + '\n',
    )

    // Sentinel values, so a leak is unmistakable rather than plausible.
    // Two defences, and they catch different mistakes.
    //
    // It refuses a non-`--only-names` call by *exit code*, not by a message:
    // the script runs doppler with `2>/dev/null`, so a stub that complained on
    // stderr would be silenced. A non-zero exit is the one signal the script
    // cannot discard -- it takes the "cannot be read" branch and every passing
    // case turns red.
    //
    // And the names payload carries a sentinel *value* anyway, even though
    // `--only-names` means a real Doppler would not. That is deliberate: it
    // makes the harness a more generous Doppler than the real one, so anything
    // the script echoes out of `$present` -- a debugging `echo "$present"`, a
    // dumped payload in an error path -- shows up in the output. Without it the
    // value-safety assertion had nothing to find and passed against a validator
    // that had been broken on purpose.
    const stub = `#!/usr/bin/env bash
if [ "$1" = "secrets" ]; then
  for arg in "$@"; do
    if [ "$arg" = "--only-names" ]; then
      printf '%s' '${JSON.stringify(
        Object.fromEntries(options.present.map((n) => [n, { computed: 'SENTINEL-LEAKED-VALUE' }])),
      )}'
      exit 0
    fi
  done
  echo "STUB REFUSED: doppler was asked for values, not names" >&2
  exit 3
fi
exit 0
`
    const stubPath = join(root, 'stub', 'doppler')
    writeFileSync(stubPath, stub)
    chmodSync(stubPath, 0o755)

    try {
      const stdout = execFileSync('bash', [join(root, 'local', 'scripts', 'doppler-check.sh'), 'dev'], {
        encoding: 'utf8',
        env: { ...process.env, PATH: `${join(root, 'stub')}:${process.env.PATH ?? ''}` },
        stdio: ['ignore', 'pipe', 'pipe'],
      })
      return { status: 0, stdout, stderr: '' }
    } catch (error) {
      const failure = error as { status?: number; stdout?: string; stderr?: string }
      return {
        status: failure.status ?? 1,
        stdout: failure.stdout ?? '',
        stderr: failure.stderr ?? '',
      }
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

/** Every name a profile's manifest requires: neither local nor optional. */
function required(profile: Profile): string[] {
  return manifest(profile)
    .filter((entry) => entry.klass !== 'local' && entry.klass !== 'optional')
    .map((entry) => entry.name)
}

describe('doppler-check refuses a config holding a local-only setting', () => {
  it('passes when every required name is present and no local one is', () => {
    const result = runCheck({ profile: 'product', present: required('product') })
    expect(result.status, result.stdout + result.stderr).toBe(0)
    expect(result.stdout).toContain('complete')
  })

  it('passes when an optional name is present, and when it is absent', () => {
    const withOptional = runCheck({
      profile: 'product',
      present: [...required('product'), 'SMTP_HOST', 'SMTP_FROM'],
    })
    expect(withOptional.status, withOptional.stdout + withOptional.stderr).toBe(0)
    const without = runCheck({ profile: 'product', present: required('product') })
    expect(without.status).toBe(0)
  })

  it('fails when NODE_ENV is present, and says so by name', () => {
    // PLAT-DEF-014's central criterion.
    const result = runCheck({ profile: 'product', present: [...required('product'), 'NODE_ENV'] })
    expect(result.status).not.toBe(0)
    expect(result.stdout + result.stderr).toContain('NODE_ENV')
  })

  it('fails for any local-only setting, not only the one that was found', () => {
    for (const name of ['MINIO_ROOT_PASSWORD', 'ZITADEL_MASTERKEY', 'GRAFANA_PASSWORD']) {
      const result = runCheck({ profile: 'product', present: [...required('product'), name] })
      expect(result.status, `${name} was tolerated`).not.toBe(0)
      expect(result.stdout + result.stderr).toContain(name)
    }
  })

  it('reports every offending name, not just the first', () => {
    const result = runCheck({
      profile: 'product',
      present: [...required('product'), 'NODE_ENV', 'MINIO_ROOT_USER'],
    })
    expect(result.status).not.toBe(0)
    const output = result.stdout + result.stderr
    expect(output).toContain('NODE_ENV')
    expect(output).toContain('MINIO_ROOT_USER')
  })

  it('keeps failing when a required name is missing', () => {
    // The behaviour that already existed. A new rule that quietly replaced it
    // would trade one silent deployment for another.
    const names = required('product')
    const result = runCheck({ profile: 'product', present: names.slice(1) })
    expect(result.status).not.toBe(0)
    expect(result.stdout + result.stderr).toContain(names[0] as string)
  })

  it('lets the Control Plane keep the mail settings it reads', () => {
    // The regression this whole reclassification exists to prevent.
    const result = runCheck({
      profile: 'control-plane',
      present: [...required('control-plane'), 'SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURE', 'SMTP_FROM'],
    })
    expect(result.status, result.stdout + result.stderr).toBe(0)
  })

  it('still forbids NODE_ENV in the Control Plane', () => {
    const result = runCheck({
      profile: 'control-plane',
      present: [...required('control-plane'), 'NODE_ENV'],
    })
    expect(result.status).not.toBe(0)
    expect(result.stdout + result.stderr).toContain('NODE_ENV')
  })

  it('asks Doppler for names and never for values', () => {
    // The property that keeps every other assertion here safe to run in CI.
    // The stub refuses any call that is not `--only-names` by exiting non-zero,
    // so a checker that started fetching values takes the "cannot be read"
    // branch and every passing case below turns red.
    //
    // Asserted through behaviour rather than by grepping the source for the
    // flag: the source can carry the flag on a line that no longer runs.
    const result = runCheck({ profile: 'product', present: required('product') })
    expect(result.status, result.stdout + result.stderr).toBe(0)
    expect(result.stdout).toContain('complete')
    expect(result.stdout + result.stderr).not.toContain('cannot be read')
  })

  it('never puts a value in its output, on the failing path or the passing one', () => {
    // The stub's payload carries a sentinel value, so anything the script
    // echoes out of `$present` appears here. Both paths are checked because
    // they print different things and only one of them was ever exercised.
    const failing = runCheck({
      profile: 'product',
      present: [...required('product'), 'NODE_ENV', 'MINIO_ROOT_PASSWORD'],
    })
    expect(failing.status).not.toBe(0)
    expect(failing.stdout).not.toContain('SENTINEL-LEAKED-VALUE')
    expect(failing.stderr).not.toContain('SENTINEL-LEAKED-VALUE')

    const passing = runCheck({ profile: 'product', present: required('product') })
    expect(passing.status).toBe(0)
    expect(passing.stdout).not.toContain('SENTINEL-LEAKED-VALUE')
    expect(passing.stderr).not.toContain('SENTINEL-LEAKED-VALUE')
  })
})

// ── the ordering that makes the check a gate ─────────────────────────────────

describe('the settings check runs before anything reaches a provider', () => {
  /**
   * The rule is only a gate if it runs first, and here it already does -- so
   * this asserts the property rather than changing the workflow. `deploy.yml`
   * is one file with a `needs:` graph, and the guarantee comes from that graph
   * rather than from step order: `settings` -> `migrate` -> `services` ->
   * `applications`. Break a link and a Vercel or Fly mutation could start while
   * the config was still unchecked.
   */
  const workflow = load(
    join(
      templatePath('product', 'package.json.hbs'),
      '..',
      '..',
      '..',
      '_shared',
      'template',
      '.github',
      'workflows',
      'deploy.yml',
    ),
  )

  /** Every job `name` reaches, following `needs` to the root. */
  function ancestors(name: string): Set<string> {
    const jobs = workflow.jobs
    const seen = new Set<string>()
    const walk = (job: string): void => {
      const needs = jobs[job]?.needs
      const list = needs === undefined ? [] : Array.isArray(needs) ? needs : [needs]
      for (const parent of list) {
        if (seen.has(parent)) continue
        seen.add(parent)
        walk(parent)
      }
    }
    walk(name)
    return seen
  }

  it('runs doppler-check in the settings job', () => {
    const steps = workflow.jobs.settings.steps
    expect(steps.some((step) => (step.run ?? '').includes('doppler-check.sh'))).toBe(true)
  })

  it('puts settings ahead of every job that mutates a provider', () => {
    // Named rather than discovered: a new job that deploys something is a
    // deliberate act, and adding it here is the moment to ask whether it is
    // downstream of the check.
    for (const job of ['migrate', 'services', 'applications']) {
      expect(ancestors(job), `${job} does not depend on settings`).toContain('settings')
    }
  })

  it('finds the provider mutations it claims to protect', () => {
    // Otherwise the assertion above guards jobs that do nothing.
    const mutating = (job: string): boolean =>
      (workflow.jobs[job]?.steps ?? []).some((step) =>
        /vercel|flyctl|fly deploy|fly secrets/i.test(step.run ?? ''),
      )
    expect(mutating('services'), 'services mutates no provider').toBe(true)
    expect(mutating('applications'), 'applications mutates no provider').toBe(true)
  })
})
