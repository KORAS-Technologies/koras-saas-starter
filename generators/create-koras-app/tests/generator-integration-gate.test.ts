import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
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
    // Read by the starter-side install, build and generation, and named by no
    // rule until PR #69's review.
    ['package.json'],
    ['pnpm-lock.yaml'],
    ['pnpm-workspace.yaml'],
    ['turbo.json'],
    ['.npmrc'],
    ['.pnpmfile.cjs'],
    ['.claude/skills/koras-auth/SKILL.md'],
    ['.claude/CLAUDE.md'],
    ['tooling/postman/extract.py'],
    ['tsconfig.base.json'],
    ['apps/web/package.json'],
    ['packages/ui/package.json'],
    ['services/api/package.json'],
    ['tooling/koras-cli/package.json'],
    ['tests/e2e/package.json'],
    ['tests/docs/package.json'],
    ['pyproject.toml'],
    ['uv.toml'],
    ['.gitattributes'],
  ])('%s is relevant', (path) => {
    expect(isRelevant([path])).toBe(true)
  })

  it.each([
    ['docs/FOLLOW_UPS.md'],
    ['CLAUDE.md'],
    ['README.md'],
    ['.github/workflows/ci.yml'],
    ['.github/workflows/generator-integration.yml.bak'],
    ['infrastructure/terraform/environments/dev/main.tf'],
    // A prefix is a directory, not a string: these share the letters only.
    ['generators-old/x.ts'],
    ['profilesX/a'],
    ['.claude-old/x.md'],
    // An exact path is exact.
    ['package.json.bak'],
    ['docs/package.json'],
    ['docs/turbo.json'],
    ['services/api/pyproject.toml'],
    // A `*` is one segment: a workspace package's source is not its manifest,
    // and neither is a manifest nested below one.
    ['apps/web/src/app/page.tsx'],
    ['apps/web/node_modules/x/package.json'],
    ['apps/package.json'],
    ['apps/web/package.json/x'],
    ['packages/ui/package.json.orig'],
    ['tooling/koras-cli/src/index.ts'],
    ['tests/unit/package.json'],
  ])('%s is not', (path) => {
    expect(isRelevant([path])).toBe(false)
  })

  it('uses `*` only as a whole segment', () => {
    // matches() compares segment by segment; `foo*` would be compared literally
    // and silently match nothing.
    for (const rule of RELEVANT_PATHS.filter((r) => r.includes('*'))) {
      for (const part of rule.split('/')) {
        if (part.includes('*')) expect(part, rule).toBe('*')
      }
    }
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

/**
 * The list above is only as good as somebody's memory of what the workflow
 * reads, and a missing entry fails open: the jobs are skipped and the gate
 * passes. These derive the inputs from the files that declare them, so a
 * shared asset, a workspace glob, a local action or a script added later
 * without a rule here goes red.
 */
describe('every input the workflow is known to read is relevant', () => {
  const read = (...parts: string[]) => readFileSync(join(REPO, ...parts), 'utf8').split(CR).join('')
  const workflow = read('.github', 'workflows', 'generator-integration.yml')
  const sample = (dir: string) => `${dir.replace(/\/$/, '')}/x.txt`

  it.each(['product', 'control-plane'])('every shared_asset of the %s profile', (profile) => {
    const manifest = yaml.load(read('profiles', profile, 'manifest.yaml')) as { shared_assets?: { source: string }[] }
    const sources = (manifest.shared_assets ?? []).map((asset) => asset.source)
    expect(sources).toContain('.claude')
    for (const source of sources) expect(isRelevant([sample(source)]), source).toBe(true)
  })

  it('every workspace package manifest the starter install resolves', () => {
    const globs = (yaml.load(read('pnpm-workspace.yaml')) as { packages: string[] }).packages
    expect(globs.length).toBeGreaterThan(0)
    for (const glob of globs) {
      // A `*` rule is one segment; `**` or a negation would need rules this
      // file does not have, so either is refused rather than half-checked.
      expect(glob, glob).not.toMatch(/\*\*|^!/)
      const manifest = `${glob.split('*').join('some-package')}/package.json`
      expect(isRelevant([manifest]), manifest).toBe(true)
    }
  })

  it("the config the generator's own build extends", () => {
    const tsconfig = JSON.parse(read('generators', 'create-koras-app', 'tsconfig.json')) as { extends?: string }
    expect(tsconfig.extends).toBeDefined()
    const resolved = join('generators', 'create-koras-app', tsconfig.extends!).split('\\').join('/')
    expect(isRelevant([resolved]), resolved).toBe(true)
  })

  /**
   * Structural rather than by spelling: every step that does not run inside
   * the generated project under runner.temp is split into tokens, and any
   * token, `uses: ./`, `with:` value or `working-directory` that names a path
   * existing in the starter must be relevant. A regex over `node .github/...`
   * missed `bash ./.github/...`, `"${GITHUB_WORKSPACE}/..."`, a quoted local
   * action and any starter path outside .github/.
   */
  it('every starter path a step runs, copies, enters or uses', () => {
    type Step = { uses?: string; run?: string; with?: Record<string, unknown>; 'working-directory'?: string }
    const doc = yaml.load(workflow) as { jobs: Record<string, { steps?: Step[] }> }
    const WORKSPACE = /^(?:\$\{\{\s*github\.workspace\s*\}\}|\$\{GITHUB_WORKSPACE\}|\$GITHUB_WORKSPACE)\//
    const normalise = (token: string) =>
      token.replace(/^["']+|["']+$/g, '').replace(WORKSPACE, '').replace(/^(?:\.\/)+/, '').replace(/\/+$/, '')
    const named = new Set<string>()
    /** `anchored`: only a path spelled from the workspace counts. */
    const consider = (raw: string, anchored = false) => {
      if (anchored && !WORKSPACE.test(raw.replace(/^["']+/, ''))) return
      const path = normalise(raw)
      // A `\` is a shell line continuation, and resolves to a drive root on Windows.
      if (!path || path === '.' || path.startsWith('..') || /[$*{}\\]/.test(path)) return
      if (!existsSync(join(REPO, path))) return
      named.add(statSync(join(REPO, path)).isDirectory() ? `${path}/x.txt` : path)
    }
    for (const job of Object.values(doc.jobs)) {
      for (const step of job.steps ?? []) {
        const wd = step['working-directory']
        // Inside the generated project a bare relative path is the project's,
        // not the starter's; only a workspace-anchored one reaches back.
        const inProject = wd?.includes('runner.temp') ?? false
        if (wd && !inProject) consider(wd)
        if (step.uses?.startsWith('./')) consider(step.uses)
        // `${{ github.workspace }}` has spaces inside it, so it is made one
        // token before the text is split on whitespace.
        const tokens = (text: string) => text.replace(/\$\{\{\s*github\.workspace\s*\}\}/g, '$GITHUB_WORKSPACE').split(/[\s;|&()<>]+/)
        for (const value of Object.values(step.with ?? {})) {
          for (const token of tokens(String(value))) consider(token, inProject)
        }
        for (const token of tokens(step.run ?? '')) consider(token, inProject)
      }
    }
    // What this was written against, so an extraction that quietly finds
    // nothing cannot pass.
    expect([...named]).toEqual(
      expect.arrayContaining([
        '.github/actions/start-minio/x.txt',
        '.github/fixtures/import-target.py',
        '.github/fixtures/import-run.sql',
        '.github/scripts/local-zitadel-secure/signin.mjs',
        '.github/scripts/local-zitadel-secure/run.sh',
        '.github/scripts/generator-integration-gate/gate.mjs',
        '.github/scripts/generator-integration-gate/x.txt',
        'generators/create-koras-app/x.txt',
      ]),
    )
    for (const path of named) expect(isRelevant([path]), path).toBe(true)
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

  it.each([undefined, null, '', 'neutral', 'Success', 'timed_out'])(
    'refuses a job result it does not know, %j, whatever detection said',
    (result) => {
      // An allowlist, not a denylist: a result GitHub adds later, or a job
      // whose entry is malformed, must not read as a pass.
      for (const relevant of ['true', 'false']) {
        const needs = { changes: changes(relevant), ...jobs(relevant === 'true' ? 'success' : 'skipped'), 'generate-and-build': { result } }
        expect(verdict(needs).ok, `relevant=${relevant}`).toBe(false)
      }
      expect(verdict({ changes: changes('true'), ...jobs('success'), 'local-zitadel-secure': null }).ok).toBe(false)
    },
  )

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

/**
 * A real repository with a base commit, so detection runs real `git diff`.
 *
 * Commits are built through a private index (read-tree, update-index,
 * write-tree, commit-tree) rather than by checking out branches: nothing
 * touches a working tree, so a name Windows cannot hold on disk -- a `"`, a
 * tab -- is committed exactly like any other, and the per-rule cases stay cheap.
 */
describe('detection against a real repository', () => {
  let repo: string
  let base: string
  let output: string
  const scratch: string[] = []

  const git = (args: string[], options: { env?: NodeJS.ProcessEnv; input?: string } = {}) =>
    execFileSync('git', args, { cwd: repo, encoding: 'utf8', env: options.env ?? process.env, input: options.input }).trim()

  /** A commit on `parent` with `files` written and `remove` deleted. */
  const commit = (parent: string, files: Record<string, string>, remove: string[] = []): string => {
    const env = { ...process.env, GIT_INDEX_FILE: join(repo, '.git', `index-${Math.random().toString(36).slice(2)}`) }
    git(['read-tree', parent], { env })
    for (const path of remove) git(['update-index', '--force-remove', '--', path], { env })
    for (const [path, content] of Object.entries(files)) {
      const blob = git(['hash-object', '-w', '--stdin'], { input: content })
      // Git for Windows refuses some of these names under core.protectNTFS,
      // which guards a working tree; nothing here reaches one.
      git(['-c', 'core.protectNTFS=false', 'update-index', '--add', '--cacheinfo', `100644,${blob},${path}`], { env })
    }
    const tree = git(['write-tree'], { env })
    return git(['commit-tree', tree, '-p', parent, '-m', 'change'])
  }
  const pr = (head: string, from = base) => detect({ EVENT_NAME: 'pull_request', BASE_SHA: from, HEAD_SHA: head }, repo)
  const push = (head: string, before = base) => detect({ EVENT_NAME: 'push', BEFORE_SHA: before, HEAD_SHA: head }, repo)
  const cli = (mode: 'detect' | 'verdict', env: Record<string, string | undefined>, options: { cwd?: string; script?: string } = {}) =>
    spawnSync(process.execPath, [options.script ?? SCRIPT, mode], {
      cwd: options.cwd ?? repo,
      env: { ...process.env, GITHUB_OUTPUT: output, ...env },
      encoding: 'utf8',
    })

  beforeAll(() => {
    repo = mkdtempSync(join(tmpdir(), 'gi-gate-'))
    scratch.push(repo)
    // No template and no hooks: the global config of whoever runs this must
    // not run code inside the test.
    execFileSync('git', ['init', '-q', '--template=', repo])
    const hooks = mkdtempSync(join(tmpdir(), 'gi-gate-hooks-'))
    scratch.push(hooks)
    for (const [key, value] of [
      ['user.email', 'gate@example.invalid'],
      ['user.name', 'gate'],
      ['commit.gpgsign', 'false'],
      ['core.autocrlf', 'false'],
      ['core.hooksPath', hooks],
    ]) {
      git(['config', key!, value!])
    }
    const empty = git(['hash-object', '-t', 'tree', '-w', '--stdin'], { input: '' })
    const root = git(['commit-tree', empty, '-m', 'root'])
    base = commit(root, { 'docs/README.md': 'docs\n', 'profiles/product/template/a.txt': 'a\n' })
    output = join(repo, '.git', 'github-output')
  })

  afterAll(() => {
    for (const dir of scratch) rmSync(dir, { recursive: true, force: true })
  })

  it('a docs-only pull request is not relevant', () => {
    const result = pr(commit(base, { 'docs/README.md': 'changed\n' }))
    expect(result.relevant).toBe(false)
    expect(result.paths).toEqual(['docs/README.md'])
  })

  it('a pull request touching a profile is relevant', () => {
    expect(pr(commit(base, { 'docs/README.md': 'also\n', 'profiles/product/template/a.txt': 'b\n' })).relevant).toBe(true)
  })

  it('moving a file out of a profile is relevant', () => {
    const head = commit(base, { 'docs/a.txt': 'a\n' }, ['profiles/product/template/a.txt'])
    const result = pr(head)
    expect(result.relevant).toBe(true)
    expect(result.paths).toContain('profiles/product/template/a.txt')
  })

  it('compares from the merge base, so later commits on the base do not count', () => {
    const head = commit(base, { 'docs/late.md': 'x\n' })
    // The base moves on with a profile change the pull request does not carry.
    const moved = commit(base, { 'profiles/product/template/a.txt': 'moved\n' })
    expect(pr(head, moved).relevant).toBe(false)
  })

  it('a push is compared with the commit before it', () => {
    expect(push(commit(base, { 'docs/p.md': 'p\n' })).relevant).toBe(false)
    expect(push(commit(base, { 'profiles/x.txt': 'x\n' })).relevant).toBe(true)
  })

  it('fails closed: a push it cannot compare runs everything', () => {
    const head = commit(base, { 'docs/n.md': 'n\n' })
    expect(push(head, '0'.repeat(40)).relevant).toBe(true)
    expect(push(head, 'f'.repeat(40)).relevant).toBe(true)
    expect(push(head, '').relevant).toBe(true)
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
    expect(() => pr(base, 'e'.repeat(40))).toThrow()
  })

  /**
   * One sample path per rule, committed alone and put through a real `git
   * diff` for both events, so every rule is proven to trigger the expensive
   * jobs rather than only through isRelevant(). The explicit lists above are
   * what fail when a rule is deleted; this is what fails when a rule exists
   * and git's output does not reach it.
   */
  it.each(RELEVANT_PATHS)('the rule %j triggers Generator Integration through a real diff', (rule) => {
    const path = rule.endsWith('/') ? `${rule}sample.txt` : rule.split('/').map((p) => (p === '*' ? 'sample-pkg' : p)).join('/')
    const head = commit(base, { [path]: `${rule}\n` })
    const result = pr(head)
    expect(result.paths).toEqual([path])
    expect(result.relevant).toBe(true)
    expect(push(head).relevant).toBe(true)
  })

  /**
   * By default git C-quotes a path with a byte above 0x7F, a `"`, a `\` or a
   * control character, and a quoted path starts with `"` and matches no rule.
   * That was a fail-open: a change to an accented template skipped every job.
   */
  it.each([
    'profiles/product/template/messages/français.json',
    'generators/create-koras-app/src/日本.ts',
    'profiles/with space.txt',
    'profiles/a"quote.txt',
    'profiles/back\\slash.txt',
    'generators/tab\there.ts',
    'profiles/new\nline.txt',
  ])('a path git would quote is still read as itself: %j', (path) => {
    const result = pr(commit(base, { [path]: 'q\n' }))
    expect(result.paths).toEqual([path])
    expect(result.relevant).toBe(true)
  })

  it('logs a path with a newline as one JSON string, so it cannot forge a workflow command', () => {
    const head = commit(base, { 'docs/x\n::error::forged.md': 'x\n' })
    writeFileSync(output, '')
    const run = cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head })
    expect(run.status).toBe(0)
    expect(run.stdout.split('\n').some((line) => line.startsWith('::'))).toBe(false)
    expect(run.stdout).toContain(JSON.stringify('docs/x\n::error::forged.md'))
  })

  it('a pull request of docs, root prose and other workflows safely skips the expensive jobs', () => {
    const result = pr(
      commit(base, {
        'docs/FOLLOW_UPS.md': 'f\n',
        'docs/adr/0099-x.md': 'x\n',
        'CLAUDE.md': 'c\n',
        'README.md': 'r\n',
        '.github/workflows/ci.yml': 'name: CI\n',
        'apps/web/src/app/page.tsx': 'export {}\n',
      }),
    )
    expect(result.paths).toHaveLength(6)
    expect(result.relevant).toBe(false)
  })

  it('the whole pipeline: detection feeds the verdict exactly as the workflow wires it', () => {
    const docs = commit(base, { 'docs/pipe.md': 'p\n' })
    const lock = commit(base, { 'pnpm-lock.yaml': 'lockfileVersion: 9\n' })
    const pipeline = (head: string, jobResult: (relevant: string) => string) => {
      writeFileSync(output, '')
      expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head }).status).toBe(0)
      const relevant = /^relevant=(true|false)$/m.exec(readFileSync(output, 'utf8'))![1]!
      const needs = { changes: changes(relevant), ...jobs(jobResult(relevant)) }
      return { relevant, status: cli('verdict', { NEEDS: JSON.stringify(needs) }).status }
    }
    // The `if:` on every expensive job: run when relevant, skip otherwise.
    const asWired = (relevant: string) => (relevant === 'true' ? 'success' : 'skipped')
    expect(pipeline(docs, asWired)).toEqual({ relevant: 'false', status: 0 })
    expect(pipeline(lock, asWired)).toEqual({ relevant: 'true', status: 0 })
    // A lockfile change whose jobs were skipped -- the defect PR #69's review
    // fixed, seen from the gate -- or failed or cancelled, is refused.
    for (const result of ['skipped', 'failure', 'cancelled']) {
      expect(pipeline(lock, () => result), result).toEqual({ relevant: 'true', status: 1 })
    }
  })

  it('a detection error fails the step and writes no answer', () => {
    const head = commit(base, { 'docs/e.md': 'e\n' })
    const notARepo = mkdtempSync(join(tmpdir(), 'gi-gate-norepo-'))
    scratch.push(notARepo)
    writeFileSync(output, '')
    // Not a repository, as with a checkout that never happened.
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head }, { cwd: notARepo }).status).not.toBe(0)
    // A malformed SHA, an absent one, and a missing one.
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: 'main' }).status).not.toBe(0)
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: 'a'.repeat(40) }).status).not.toBe(0)
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: undefined, HEAD_SHA: head }).status).not.toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('')
    // Nowhere to write the answer: the job fails rather than leaving the output empty.
    expect(cli('detect', { GITHUB_OUTPUT: '', EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: head }).status).not.toBe(0)
  })

  it('writes its answer for the workflow, and exits non-zero when it cannot', () => {
    const docs = commit(base, { 'docs/c.md': 'c\n' })
    const profile = commit(base, { 'profiles/c.md': 'c\n' })
    writeFileSync(output, '')
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: docs }).status).toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('relevant=false\n')
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: 'e'.repeat(40), HEAD_SHA: docs }).status).not.toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('relevant=false\n')
    writeFileSync(output, '')
    expect(cli('detect', { EVENT_NAME: 'pull_request', BASE_SHA: base, HEAD_SHA: profile }).status).toBe(0)
    expect(readFileSync(output, 'utf8')).toBe('relevant=true\n')
  })

  /**
   * Node resolves a module's own URL to its real path and leaves argv[1] as
   * typed, so an entry guard comparing the two never ran main() when the
   * script was reached through a link -- and the verdict exited 0 having
   * judged nothing. A junction needs no privilege on Windows; elsewhere it is
   * an ordinary directory symlink.
   */
  it('runs, and refuses, when started through a link to its directory', () => {
    const linkParent = mkdtempSync(join(tmpdir(), 'gi-gate-link-'))
    scratch.push(linkParent)
    const link = join(linkParent, 'gate')
    symlinkSync(dirname(SCRIPT), link, 'junction')
    const linked = join(link, 'gate.mjs')
    const refused = cli('verdict', { NEEDS: JSON.stringify({ changes: changes('true'), ...jobs('failure') }) }, { script: linked })
    expect(refused.stdout).toContain('Generator Integration: refused')
    expect(refused.status).toBe(1)
    const passed = cli('verdict', { NEEDS: JSON.stringify({ changes: changes('false'), ...jobs('skipped') }) }, { script: linked })
    expect(passed.stdout).toContain('Generator Integration: pass')
    expect(passed.status).toBe(0)
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

  it('reruns when a pull request is retargeted, as well as on every push to it', () => {
    // A base change fires only `edited`. Without it the check computed
    // against the old base stays green on the head.
    const types = (doc.on.pull_request as { types?: string[] } | null)?.types
    expect([...(types ?? [])].sort()).toEqual(['edited', 'opened', 'reopened', 'synchronize'])
  })

  it('no job the gate judges can turn its own failure into a success', () => {
    // `continue-on-error` on a job reports `success` in `needs` when it fails.
    for (const [id, job] of Object.entries(doc.jobs)) {
      expect(job, id).not.toHaveProperty('continue-on-error')
    }
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

  it('no job in any other workflow is named Generator Integration either', () => {
    // A required check matches by name, so a job of that name anywhere would
    // satisfy it.
    const dir = join(REPO, '.github', 'workflows')
    const others = readdirSync(dir).filter((f) => /\.ya?ml$/.test(f) && f !== 'generator-integration.yml')
    expect(others.length).toBeGreaterThan(0)
    for (const file of others) {
      const other = yaml.load(readFileSync(join(dir, file), 'utf8')) as { jobs?: Record<string, Job> }
      for (const [id, job] of Object.entries(other.jobs ?? {})) {
        expect(job.name ?? id, `${file}:${id}`).not.toBe('Generator Integration')
      }
    }
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
