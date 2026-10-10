import { describe, it, expect, beforeAll } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import yaml from 'js-yaml'
import { detect, isRelevant, verdict, RELEVANT_PATHS } from '../../../.github/scripts/generator-integration-gate/gate.mjs'

/**
 * The aggregate gate for Generator Integration (F32).
 *
 * The workflow used to be path-filtered at the trigger, so a pull request that
 * touched none of its paths produced no check, and a required check that never
 * reports blocks a pull request for good. It now always starts, a `changes` job
 * decides whether the expensive jobs run, and one job named `Generator
 * Integration` judges them. What has to hold is that it fails closed: a
 * relevant change cannot pass by being cancelled, skipped, or never detected.
 */

const REPO = join(__dirname, '..', '..', '..')
const SCRIPT = join(REPO, '.github', 'scripts', 'generator-integration-gate', 'gate.mjs')
const CR = String.fromCharCode(13)

describe('which paths are relevant', () => {
  it.each([
    ['profiles/product/template/package.json.hbs'],
    ['generators/create-koras-app/src/cli.ts'],
    ['infrastructure/terraform/modules/github/main.tf'],
    ['.github/workflows/generator-integration.yml'],
    ['.github/scripts/local-zitadel-secure/run.sh'],
    ['.github/scripts/generator-integration-gate/gate.mjs'],
    ['.github/actions/start-minio/action.yml'],
    ['.github/fixtures/import-target.py'],
  ])('%s is relevant', (path) => {
    expect(isRelevant([path])).toBe(true)
  })

  it.each([
    ['docs/FOLLOW_UPS.md'],
    ['CLAUDE.md'],
    ['.github/workflows/ci.yml'],
    ['.github/workflows/generator-integration.yml.bak'],
    ['infrastructure/terraform/environments/dev/main.tf'],
    // A prefix is a directory, not a string: these share the letters only.
    ['generators-old/x.ts'],
    ['profilesX/a'],
  ])('%s is not', (path) => {
    expect(isRelevant([path])).toBe(false)
  })

  it('one relevant path among many is enough, and none is not', () => {
    expect(isRelevant(['docs/a.md', 'README.md', 'profiles/_shared/template/x'])).toBe(true)
    expect(isRelevant(['docs/a.md', 'README.md'])).toBe(false)
    expect(isRelevant([])).toBe(false)
  })

  it('keeps every path the trigger filter it replaced named', () => {
    // generators/**, profiles/**, infrastructure/terraform/modules/**, the
    // workflow itself and the local-zitadel-secure scripts.
    for (const rule of [
      'generators/',
      'profiles/',
      'infrastructure/terraform/modules/',
      '.github/workflows/generator-integration.yml',
      '.github/scripts/local-zitadel-secure/',
    ]) {
      expect(RELEVANT_PATHS).toContain(rule)
    }
  })
})

const changes = (relevant: string | undefined, result = 'success') => ({
  result,
  outputs: relevant === undefined ? {} : { relevant },
})
const jobs = (result: string) => ({
  'generate-and-build': { result, outputs: {} },
  'local-zitadel-secure': { result, outputs: {} },
  'local-zitadel-secure-windows': { result, outputs: {} },
})

describe('the verdict', () => {
  it('passes a docs-only change whose jobs were skipped', () => {
    expect(verdict({ changes: changes('false'), ...jobs('skipped') }).ok).toBe(true)
  })

  it('passes a relevant change whose jobs all succeeded', () => {
    expect(verdict({ changes: changes('true'), ...jobs('success') }).ok).toBe(true)
  })

  it.each(['failure', 'cancelled', 'skipped'])('refuses a relevant change with one job %s', (result) => {
    const needs = { changes: changes('true'), ...jobs('success'), 'local-zitadel-secure': { result, outputs: {} } }
    const outcome = verdict(needs)
    expect(outcome.ok).toBe(false)
    expect(outcome.lines.join('\n')).toContain(`REFUSE local-zitadel-secure: ${result}`)
  })

  it.each(['failure', 'cancelled'])('refuses an irrelevant change with a job %s', (result) => {
    const needs = { changes: changes('false'), ...jobs('skipped'), 'generate-and-build': { result, outputs: {} } }
    expect(verdict(needs).ok).toBe(false)
  })

  it.each(['failure', 'cancelled', 'skipped'])('refuses when detection itself is %s', (result) => {
    // The jobs downstream of a failed detection are skipped, which for an
    // irrelevant change would read as a pass. Detection must have succeeded.
    expect(verdict({ changes: changes('false', result), ...jobs('skipped') }).ok).toBe(false)
    expect(verdict({ changes: changes(undefined, result), ...jobs('skipped') }).ok).toBe(false)
  })

  it.each([undefined, '', 'yes', 'True'])('refuses a detection answer of %j', (answer) => {
    expect(verdict({ changes: changes(answer), ...jobs('skipped') }).ok).toBe(false)
  })

  it('refuses when there is nothing to judge, or no detection to read', () => {
    expect(verdict({ changes: changes('true') }).ok).toBe(false)
    expect(verdict({ changes: changes('false') }).ok).toBe(false)
    expect(verdict({ ...jobs('success') }).ok).toBe(false)
    expect(verdict(null).ok).toBe(false)
  })

  it('exits 0 or 1 as the workflow runs it, and 1 on NEEDS that is not JSON', () => {
    const run = (needs: string) =>
      spawnSync(process.execPath, [SCRIPT, 'verdict'], { env: { ...process.env, NEEDS: needs }, encoding: 'utf8' })
    expect(run(JSON.stringify({ changes: changes('false'), ...jobs('skipped') })).status).toBe(0)
    expect(run(JSON.stringify({ changes: changes('true'), ...jobs('success') })).status).toBe(0)
    const refused = run(JSON.stringify({ changes: changes('true'), ...jobs('cancelled') }))
    expect(refused.status).toBe(1)
    expect(refused.stdout).toContain('Generator Integration: refused')
    expect(run('not json').status).toBe(1)
    expect(run('').status).toBe(1)
  })
})

/** A real repository with a base commit, so detection runs real `git diff`. */
describe('detection against a real repository', () => {
  let repo: string
  let base: string

  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
  const write = (path: string, content: string) => {
    mkdirSync(dirname(join(repo, path)), { recursive: true })
    writeFileSync(join(repo, path), content)
  }
  /** Branch from base, make `edit`, commit, return the head and go back. */
  const branch = (name: string, edit: () => void): string => {
    git('checkout', '-q', '-b', name, base)
    edit()
    git('add', '-A')
    git('commit', '-q', '-m', name)
    const head = git('rev-parse', 'HEAD')
    git('checkout', '-q', base)
    return head
  }
  const pr = (head: string) => detect({ EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head }, repo)

  beforeAll(() => {
    repo = mkdtempSync(join(tmpdir(), 'gi-gate-'))
    git('init', '-q')
    git('config', 'user.email', 'gate@example.invalid')
    git('config', 'user.name', 'gate')
    git('config', 'commit.gpgsign', 'false')
    git('config', 'core.autocrlf', 'false')
    write('docs/README.md', 'docs\n')
    write('profiles/product/template/a.txt', 'a\n')
    git('add', '-A')
    git('commit', '-q', '-m', 'base')
    base = git('rev-parse', 'HEAD')
  })

  it('a docs-only pull request is not relevant', () => {
    const head = branch('docs-only', () => write('docs/README.md', 'changed\n'))
    const result = pr(head)
    expect(result.relevant).toBe(false)
    expect(result.paths).toEqual(['docs/README.md'])
  })

  it('a pull request touching a profile is relevant', () => {
    const head = branch('profile', () => {
      write('docs/README.md', 'also docs\n')
      write('profiles/product/template/a.txt', 'b\n')
    })
    expect(pr(head).relevant).toBe(true)
  })

  it('moving a file out of a profile is relevant', () => {
    const head = branch('rename-out', () => git('mv', 'profiles/product/template/a.txt', 'docs/a.txt'))
    const result = pr(head)
    expect(result.relevant).toBe(true)
    expect(result.paths).toContain('profiles/product/template/a.txt')
  })

  it('compares from the merge base, so later commits on the base do not count', () => {
    const head = branch('docs-late', () => write('docs/late.md', 'x\n'))
    // The base moves on with a profile change the pull request does not carry.
    git('checkout', '-q', '-b', 'base-moved', base)
    write('profiles/product/template/a.txt', 'moved\n')
    git('commit', '-qam', 'base moves')
    const moved = git('rev-parse', 'HEAD')
    git('checkout', '-q', base)
    expect(detect({ EVENT_NAME: 'pull_request', BASE_SHA: moved, HEAD_SHA: head }, repo).relevant).toBe(false)
  })

  it('a push is compared with the commit before it', () => {
    const docs = branch('push-docs', () => write('docs/p.md', 'p\n'))
    const profile = branch('push-profile', () => write('profiles/x.txt', 'x\n'))
    expect(detect({ EVENT_NAME: 'push', BEFORE_SHA: base, HEAD_SHA: docs }, repo).relevant).toBe(false)
    expect(detect({ EVENT_NAME: 'push', BEFORE_SHA: base, HEAD_SHA: profile }, repo).relevant).toBe(true)
  })

  it('fails closed: a push it cannot compare runs everything', () => {
    const head = branch('push-new', () => write('docs/n.md', 'n\n'))
    const zero = '0'.repeat(40)
    const missing = 'f'.repeat(40)
    expect(detect({ EVENT_NAME: 'push', BEFORE_SHA: zero, HEAD_SHA: head }, repo).relevant).toBe(true)
    expect(detect({ EVENT_NAME: 'push', BEFORE_SHA: missing, HEAD_SHA: head }, repo).relevant).toBe(true)
    expect(detect({ EVENT_NAME: 'push', BEFORE_SHA: '', HEAD_SHA: head }, repo).relevant).toBe(true)
  })

  it('fails closed: a manual run, or an event it does not know, runs everything', () => {
    expect(detect({ EVENT_NAME: 'workflow_dispatch' }, repo).relevant).toBe(true)
    expect(detect({ EVENT_NAME: 'merge_group' }, repo).relevant).toBe(true)
    expect(detect({}, repo).relevant).toBe(true)
  })

  it('throws rather than guessing when a pull request cannot be compared', () => {
    expect(() => detect({ EVENT_NAME: 'pull_request', BASE_SHA: '', HEAD_SHA: base }, repo)).toThrow(/BASE_SHA/)
    expect(() => detect({ EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: 'HEAD' }, repo)).toThrow(/HEAD_SHA/)
    // Well-formed but absent from history: git refuses, and so does detection.
    expect(() => detect({ EVENT_NAME: 'pull_request', BASE_SHA: 'e'.repeat(40), HEAD_SHA: base }, repo)).toThrow()
  })

  it('writes its answer for the workflow, and exits non-zero when it cannot', () => {
    const head = branch('cli', () => write('docs/c.md', 'c\n'))
    const output = join(repo, '..', `gi-gate-output-${Date.now()}`)
    writeFileSync(output, '')
    const run = (env: Record<string, string>) =>
      spawnSync(process.execPath, [SCRIPT, 'detect'], {
        cwd: repo,
        env: { ...process.env, GITHUB_OUTPUT: output, ...env },
        encoding: 'utf8',
      })
    expect(run({ EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head }).status).toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('relevant=false\n')
    expect(run({ EVENT_NAME: 'pull_request', BASE_SHA: 'e'.repeat(40), HEAD_SHA: head }).status).not.toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('relevant=false\n')
  })
})

type Job = { name?: string; needs?: string | string[]; if?: string; steps?: { uses?: string; with?: Record<string, unknown>; env?: Record<string, string>; run?: string }[] }

describe('the workflow is wired to the gate', () => {
  const source = readFileSync(join(REPO, '.github', 'workflows', 'generator-integration.yml'), 'utf8').split(CR).join('')
  const doc = yaml.load(source) as { on: Record<string, Record<string, unknown> | null>; jobs: Record<string, Job> }
  const needsOf = (job: Job) => (job.needs === undefined ? [] : ([] as string[]).concat(job.needs))

  it('always starts: no path filter on any trigger', () => {
    for (const [event, config] of Object.entries(doc.on)) {
      expect(config ?? {}, event).not.toHaveProperty('paths')
      expect(config ?? {}, event).not.toHaveProperty('paths-ignore')
    }
    expect(Object.keys(doc.on).sort()).toEqual(['pull_request', 'push', 'workflow_dispatch'])
    // A branch filter on pull_request would leave pull requests to other bases
    // with no check, which is the failure this exists to remove.
    expect(doc.on.pull_request ?? {}).not.toHaveProperty('branches')
  })

  it('the gate is named for the ruleset, always runs, and judges every other job', () => {
    const gate = doc.jobs['generator-integration']
    expect(gate?.name).toBe('Generator Integration')
    expect(gate?.if).toBe('always()')
    const others = Object.keys(doc.jobs).filter((id) => id !== 'generator-integration')
    expect(needsOf(gate!).sort()).toEqual(others.sort())
    const step = gate!.steps!.find((s) => s.run?.includes('gate.mjs verdict'))
    expect(step?.env?.NEEDS).toBe('${{ toJSON(needs) }}')
  })

  it('no other job is named Generator Integration', () => {
    // GitHub names a check after the job; two jobs with that name would let
    // either one satisfy the requirement.
    const named = Object.entries(doc.jobs).filter(([, job]) => job.name === 'Generator Integration')
    expect(named.map(([id]) => id)).toEqual(['generator-integration'])
  })

  it('every expensive job waits for detection and runs only on a relevant change', () => {
    const expensive = Object.keys(doc.jobs).filter((id) => id !== 'changes' && id !== 'generator-integration')
    expect(expensive.length).toBeGreaterThanOrEqual(3)
    for (const id of expensive) {
      const job = doc.jobs[id]!
      expect(needsOf(job), id).toContain('changes')
      expect(job.if, id).toBe("needs.changes.outputs.relevant == 'true'")
    }
  })

  it('detection reads full history and passes the event through the environment', () => {
    const changes = doc.jobs.changes!
    expect(changes.if).toBeUndefined()
    const checkout = changes.steps!.find((s) => s.uses?.startsWith('actions/checkout'))
    expect(checkout?.with?.['fetch-depth']).toBe(0)
    const step = changes.steps!.find((s) => s.run?.includes('gate.mjs detect'))
    expect(step?.env).toMatchObject({
      EVENT_NAME: '${{ github.event_name }}',
      BASE_SHA: '${{ github.event.pull_request.base.sha }}',
      BEFORE_SHA: '${{ github.event.before }}',
    })
    // Values reach the script as environment, never interpolated into a shell line.
    expect(step?.run).not.toContain('${{')
  })
})
