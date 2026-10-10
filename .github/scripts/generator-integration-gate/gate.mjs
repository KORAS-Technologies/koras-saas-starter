// The aggregate gate for Generator Integration (F32).
//
// The workflow used to be path-filtered at the trigger, so a pull request that
// touched none of its paths produced no run and no check at all. A required
// check that never reports leaves a pull request unmergeable for good, which is
// why Generator Integration could not be made required. The workflow now always
// starts; `detect` decides whether the expensive jobs have anything to check,
// and `verdict` is the one check a ruleset requires.
//
// Both halves fail closed. Detection that cannot tell -- an unknown event, a
// push with no usable `before`, a diff that errors -- answers "relevant", so
// the jobs run rather than being skipped on a guess. The verdict passes only
// when detection succeeded and, for a relevant change, every job it depends on
// succeeded: `failure`, `cancelled` and `skipped` are all refusals.
//
//   node gate.mjs detect    reads the event from the environment, writes
//                           `relevant=true|false` to $GITHUB_OUTPUT
//   node gate.mjs verdict   reads NEEDS (`toJSON(needs)`), exits 1 on refusal

import { execFileSync } from 'node:child_process'
import { appendFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

/**
 * What Generator Integration reads. A directory ends in `/` and matches
 * everything under it; a `*` segment matches exactly one path segment; anything
 * else is one exact path.
 *
 * The trigger filter this replaced named only the first five, and missing a
 * path here is not harmless: a change to it skips every expensive job and the
 * gate passes. The rest were found by asking what each starter-side step
 * reads, and the tests derive as much of that as they can from the workflow,
 * the manifests and the workspace rather than from this list.
 */
export const RELEVANT_PATHS = [
  // The trigger filter this replaced.
  'generators/',
  'profiles/',
  'infrastructure/terraform/modules/',
  '.github/workflows/generator-integration.yml',
  '.github/scripts/local-zitadel-secure/',

  // Read by the workflow from the starter checkout.
  '.github/scripts/generator-integration-gate/',
  '.github/actions/start-minio/',
  '.github/fixtures/',

  // The `shared_assets` both manifests copy verbatim into every generated
  // project, beside infrastructure/terraform/modules/ above.
  '.claude/',
  'tooling/postman/',

  // `pnpm install --frozen-lockfile` and `turbo run build` at the starter
  // root. The root package.json is also where the generator reads the version
  // it stamps into .koras/project.yaml, and pnpm/action-setup reads its
  // `packageManager`.
  'package.json',
  'pnpm-lock.yaml',
  'pnpm-workspace.yaml',
  'turbo.json',
  // pnpm config the lockfile does not record (linker, hoisting, registry,
  // scripts), and the install hook. Neither exists today.
  '.npmrc',
  '.pnpmfile.cjs',
  // The generator's tsconfig.json extends it, so `turbo run build` reads it.
  'tsconfig.base.json',
  // Every workspace package's manifest is resolved by the install, and its
  // lifecycle scripts run there. One rule per glob in pnpm-workspace.yaml;
  // generators/* is covered above.
  'apps/*/package.json',
  'services/*/package.json',
  'packages/*/package.json',
  'tooling/*/package.json',
  'tests/e2e/package.json',
  'tests/docs/package.json',
  // astral-sh/setup-uv, given no version, takes `required-version` from
  // uv.toml or else pyproject.toml at the root.
  'pyproject.toml',
  'uv.toml',
  // Line endings of everything checked out, which is what the Windows job
  // tests and what the generator copies.
  '.gitattributes',
]

function matches(rule, path) {
  if (rule.endsWith('/')) return path.startsWith(rule)
  if (!rule.includes('*')) return path === rule
  const want = rule.split('/')
  const have = path.split('/')
  return want.length === have.length && want.every((part, i) => (part === '*' ? have[i] !== '' : part === have[i]))
}

export function isRelevant(paths) {
  return paths.some((path) => RELEVANT_PATHS.some((rule) => matches(rule, path)))
}

const SHA = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/
const ZERO = /^0+$/

function sha(name, value) {
  if (typeof value !== 'string' || !SHA.test(value)) {
    throw new Error(`${name} is not a commit id: ${JSON.stringify(value)}`)
  }
  return value
}

function git(cwd, ...args) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

function changedPaths(cwd, ...range) {
  // --no-renames lists a move as a deletion and an addition, so moving a file
  // out of profiles/ still counts as touching profiles/.
  //
  // -z and quotePath=false, because by default git C-quotes any path with a
  // byte above 0x7F, a `"`, a `\` or a control character: `profiles/café.md`
  // arrives as `"profiles/caf\303\251.md"`, which starts with `"` and matches
  // no rule -- so a change to an accented template skipped every job and the
  // gate passed. NUL-separated output is the one form git never quotes.
  return git(cwd, '-c', 'core.quotePath=false', 'diff', '--name-only', '-z', '--no-renames', ...range)
    .split('\0')
    .filter(Boolean)
}

/** Returns `{ relevant, reason, paths }`. Throws when it cannot read the diff. */
export function detect(env, cwd = process.cwd()) {
  const event = env.EVENT_NAME
  if (event === 'pull_request') {
    const base = sha('BASE_SHA', env.BASE_SHA)
    const head = sha('HEAD_SHA', env.HEAD_SHA)
    // Three dots: what the pull request changes since it left its base, which
    // is what GitHub's own path filter compared.
    const paths = changedPaths(cwd, `${base}...${head}`)
    return { relevant: isRelevant(paths), reason: `pull request diff ${base}...${head}`, paths }
  }
  if (event === 'push') {
    const after = sha('HEAD_SHA', env.HEAD_SHA)
    const before = env.BEFORE_SHA ?? ''
    if (!SHA.test(before) || ZERO.test(before)) {
      return { relevant: true, reason: 'push with no previous commit to compare', paths: [] }
    }
    try {
      git(cwd, 'cat-file', '-e', `${before}^{commit}`)
    } catch {
      return { relevant: true, reason: `push whose previous commit ${before} is not in history`, paths: [] }
    }
    const paths = changedPaths(cwd, before, after)
    return { relevant: isRelevant(paths), reason: `push diff ${before}..${after}`, paths }
  }
  return { relevant: true, reason: `event ${JSON.stringify(event)} always runs everything`, paths: [] }
}

/** Returns `{ ok, lines }`. `needs` is the parsed `toJSON(needs)`. */
export function verdict(needs) {
  const lines = []
  const refuse = (line) => ({ ok: false, lines: [...lines, line] })
  if (needs === null || typeof needs !== 'object') return refuse('NEEDS is not an object')

  const changes = needs.changes
  if (!changes) return refuse('the changes job is not among this job\'s needs')
  if (changes.result !== 'success') return refuse(`path detection did not succeed: ${changes.result}`)
  const answer = changes.outputs?.relevant
  if (answer !== 'true' && answer !== 'false') {
    return refuse(`path detection answered neither true nor false: ${JSON.stringify(answer)}`)
  }
  const relevant = answer === 'true'
  lines.push(`relevant: ${relevant}`)

  const jobs = Object.entries(needs).filter(([id]) => id !== 'changes')
  if (jobs.length === 0) return refuse('no jobs to judge -- the gate would pass over nothing')

  let ok = true
  for (const [id, job] of jobs) {
    const result = job?.result
    const accepted = relevant ? result === 'success' : result === 'skipped' || result === 'success'
    lines.push(`${accepted ? 'ok    ' : 'REFUSE'} ${id}: ${result}`)
    ok &&= accepted
  }
  return { ok, lines }
}

function main(argv, env) {
  const mode = argv[2]
  if (mode === 'detect') {
    const result = detect(env)
    console.log(`relevant=${result.relevant} (${result.reason})`)
    // JSON, because a path is now raw: one containing a newline could
    // otherwise start a line with `::` and be read as a workflow command.
    for (const path of result.paths) console.log(`  ${isRelevant([path]) ? '*' : ' '} ${JSON.stringify(path)}`)
    if (!env.GITHUB_OUTPUT) throw new Error('GITHUB_OUTPUT is not set')
    appendFileSync(env.GITHUB_OUTPUT, `relevant=${result.relevant}\n`)
    return 0
  }
  if (mode === 'verdict') {
    let needs
    try {
      needs = JSON.parse(env.NEEDS ?? '')
    } catch {
      console.log('REFUSE NEEDS is not JSON')
      return 1
    }
    const result = verdict(needs)
    for (const line of result.lines) console.log(line)
    console.log(result.ok ? 'Generator Integration: pass' : 'Generator Integration: refused')
    return result.ok ? 0 : 1
  }
  console.error('usage: gate.mjs detect | verdict')
  return 2
}

/**
 * Whether this file is the program rather than an import. Compared after
 * resolving links on both sides: Node resolves the module's own URL to the
 * real path and leaves argv[1] as typed, so a run through a symlink or a
 * junction compared unequal, main() never ran, and the verdict exited 0 having
 * judged nothing -- the one way this gate could pass by default.
 */
function invokedDirectly() {
  const entry = process.argv[1]
  if (!entry) return false
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(entry)
  } catch {
    return false
  }
}

if (invokedDirectly()) {
  process.exitCode = main(process.argv, process.env)
}
