#!/usr/bin/env node
/**
 * Vendors the external Claude Code skills declared in
 * `.claude/external-skills.yaml` into `.claude/skills/`.
 *
 * Deliberately not part of `create-koras-app`. Generation copies `.claude/`
 * verbatim, so a generated project inherits whatever is vendored and committed
 * — it never reaches the network to obtain its standard configuration, and it
 * never silently picks up a newer upstream than the one that was reviewed.
 *
 * Reproducibility comes from `.claude/external-skills.lock.json`: the first
 * sync resolves each declared ref to a commit and records it, and every later
 * sync installs that commit. `--update` is the only thing that moves a lock
 * entry, which makes an upgrade a reviewable diff.
 *
 * Idempotent by default: a skill already present is left alone. Nothing here
 * deletes a Koras skill, and a name collision with one is refused rather than
 * resolved.
 *
 *   node .claude/scripts/sync-external-skills.mjs [--update] [--dry-run]
 *                                                 [--skill <name>]
 */

import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, cpSync, existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const CLAUDE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const MANIFEST = join(CLAUDE_DIR, 'external-skills.yaml')
const LOCK = join(CLAUDE_DIR, 'external-skills.lock.json')

/** Skills this repository authors. Never overwritten, never removed. */
const KORAS_PREFIX = 'koras-'

const args = process.argv.slice(2)
const update = args.includes('--update')
const dryRun = args.includes('--dry-run')
const only = args.includes('--skill') ? args[args.indexOf('--skill') + 1] : null

// ── manifest ────────────────────────────────────────────────────────────────

/**
 * A deliberately small reader for the one shape this manifest has: a scalar
 * `install_path` and a list of flat string-valued maps under `skills`.
 * Pulling js-yaml in would make `.claude/` depend on the workspace's installed
 * node_modules, and this script has to run inside a freshly generated project
 * that has not installed anything yet.
 */
function readManifest(text) {
  const lines = text.split(/\r?\n/)
  let installPath = null
  const skills = []
  let current = null

  for (const raw of lines) {
    const line = raw.replace(/\s+#.*$/, '')
    if (!line.trim() || line.trim().startsWith('#')) continue

    const top = /^([a-z_]+):\s*(.*)$/.exec(line)
    if (top) {
      if (top[1] === 'install_path') installPath = top[2].trim()
      current = null
      continue
    }

    const item = /^\s*-\s*([a-z_]+):\s*(.+)$/.exec(line)
    if (item) {
      current = { [item[1]]: item[2].trim() }
      skills.push(current)
      continue
    }

    const field = /^\s+([a-z_]+):\s*(.+)$/.exec(line)
    if (field && current) current[field[1]] = field[2].trim()
  }

  if (!installPath) throw new Error(`${MANIFEST} declares no install_path.`)
  for (const s of skills) {
    for (const key of ['name', 'repo', 'path', 'ref']) {
      if (!s[key]) throw new Error(`${MANIFEST}: skill entry missing "${key}": ${JSON.stringify(s)}`)
    }
  }
  return { installPath, skills }
}

function readLock() {
  if (!existsSync(LOCK)) return { schema_version: 1, skills: {} }
  return JSON.parse(readFileSync(LOCK, 'utf8'))
}

function git(cwd, ...argv) {
  return execFileSync('git', argv, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
}

// ── sync ────────────────────────────────────────────────────────────────────

const { installPath, skills } = readManifest(readFileSync(MANIFEST, 'utf8'))
const lock = readLock()
const targetRoot = resolve(CLAUDE_DIR, '..', installPath)

const installed = []
const skipped = []
const failed = []

for (const skill of skills) {
  if (only && skill.name !== only) continue

  if (skill.name.startsWith(KORAS_PREFIX)) {
    failed.push([skill.name, `name collides with the Koras skill namespace "${KORAS_PREFIX}"`])
    continue
  }

  const target = join(targetRoot, skill.name)
  const pinned = lock.skills[skill.name]

  if (existsSync(target) && !update) {
    skipped.push([skill.name, pinned ? `already installed at ${pinned.commit.slice(0, 12)}` : 'already present'])
    continue
  }

  // `--update` re-resolves the declared ref; otherwise a locked commit wins, so
  // a fresh clone of this repository vendors exactly what was reviewed.
  const wanted = update ? skill.ref : (pinned?.commit ?? skill.ref)

  if (dryRun) {
    installed.push([skill.name, `would install ${skill.repo}#${wanted}`])
    continue
  }

  const work = mkdtempSync(join(tmpdir(), 'koras-skill-'))
  try {
    git(work, 'init', '--quiet')
    git(work, 'remote', 'add', 'origin', skill.repo)
    git(work, 'fetch', '--quiet', '--depth', '1', 'origin', wanted)
    git(work, 'checkout', '--quiet', 'FETCH_HEAD')
    const commit = git(work, 'rev-parse', 'HEAD')

    const source = join(work, skill.path)
    if (!existsSync(join(source, 'SKILL.md'))) {
      throw new Error(`${skill.repo}#${commit.slice(0, 12)} has no ${skill.path}/SKILL.md`)
    }

    rmSync(target, { recursive: true, force: true })
    mkdirSync(dirname(target), { recursive: true })
    cpSync(source, target, { recursive: true, filter: (p) => !p.split(/[\/]/).includes('.git') })

    lock.skills[skill.name] = {
      repo: skill.repo,
      path: skill.path,
      ref: skill.ref,
      commit,
      vendor: skill.vendor ?? null,
    }
    installed.push([skill.name, `${commit.slice(0, 12)} from ${skill.repo}`])
  } catch (err) {
    failed.push([skill.name, err instanceof Error ? err.message.split('\n')[0] : String(err)])
  } finally {
    rmSync(work, { recursive: true, force: true })
  }
}

if (!dryRun && installed.length > 0) {
  writeFileSync(LOCK, JSON.stringify(lock, null, 2) + '\n', 'utf8')
}

const report = (label, rows) => {
  if (rows.length === 0) return
  console.log(`\n${label}:`)
  for (const [name, detail] of rows) console.log(`  ${name.padEnd(24)} ${detail}`)
}

report(dryRun ? 'Would install' : 'Installed', installed)
report('Already present (left alone)', skipped)
report('Failed', failed)

if (failed.length > 0) {
  console.log(
    '\nExternal skills are optional. The Koras skills are complete without them,' +
      '\nand generation never requires them.',
  )
  process.exit(1)
}
console.log('')
