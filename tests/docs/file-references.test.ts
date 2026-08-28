import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A path named in a document has to exist, or be exempt for a stated reason
 * that is itself checked.
 *
 * The documents here carry an unusual share of the repository's reasoning: why
 * a thing is absent, which file holds a guard, where a credential is read. That
 * is deliberate, and it has a failure mode nothing else here has — prose is the
 * only part of this repository that can be wrong without anything going red.
 *
 * Three defects in one session came from that. A comment said ZITADEL teardown
 * "needs a service-account JWT exchange"; it had never been true, and no test
 * could have said so, because an absence has no behaviour to assert. The
 * runbook said DATABASE_ADMIN_URL was deliberately kept out of
 * `secrets.manifest` — a decision, wrong, and invisible. An audit called
 * ZITADEL_SERVICE_TOKEN an orphan because no template declared it, when the
 * missing thing was the declaration.
 *
 * A false claim about *why* still cannot be checked mechanically. A false claim
 * about *where* can, and it is the commonest kind: files move, and the document
 * that named them does not move with them.
 *
 * Deliberately narrow, so it stays worth having: only backticked tokens shaped
 * like a path with an extension — up to seven characters, because a five-limit
 * silently exempted `environments/dev.tfvars`, a file this repository has never
 * had and a document described for months; globs and `<placeholders>` skipped, since they
 * name a shape rather than a file; other repositories skipped, since this one
 * cannot see them; matched by suffix, because a document reasonably writes
 * `src/terraform/inputs.ts` for a file two package directories down.
 */

const ROOT = join(__dirname, '..', '..')

/**
 * Paths this repository does not have, named on purpose.
 *
 * Every one is asserted *absent* below. An exemption is a claim too, and a
 * document that says a file was never created is wrong the moment somebody
 * creates it — which is precisely the kind of quiet staleness this file exists
 * to catch, so it would be poor to introduce a blind spot in the escape hatch.
 */
const ABSENT_ON_PURPOSE: Record<string, string> = {
  '.koras/project.yaml': 'written by create-koras-app; the factory is not a generated project',
  'local/.env': 'written by local/scripts/ports.sh, per machine',
  'docs/AGENT_CONTEXT.md':
    'a generated project writes its own; the generator never creates or touches it',
  'local/mail/mailpit.yml': 'IMPLEMENTATION_ROADMAP records it as a deviation: never created',
  'local/storage/minio.yml': 'IMPLEMENTATION_ROADMAP records it as a deviation: never created',
  'local/certs/README.md': 'IMPLEMENTATION_ROADMAP records it as absent; generate.sh explains itself',
}

/**
 * Paths that were right when written and have since moved.
 *
 * Kept rather than rewritten. These appear in dated accounts of what was true
 * at the time — an R-036 entry describing a teardown that could not delete —
 * and editing the path would quietly falsify the record. Both halves are
 * checked: the old path must really be gone, and the replacement must really
 * exist, so this map cannot rot into a list of names nobody has looked at.
 */
const MOVED: Record<string, string> = {
  'helpers/teardown.ts': 'tooling/koras-cli/src/teardown/guards.ts',
  'tests/e2e/helpers/teardown.ts': 'tooling/koras-cli/src/teardown/guards.ts',
}

function tracked(): string[] {
  return execFileSync('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .filter(Boolean)
}

/** Every suffix of every tracked path, with `.hbs` also stripped. */
function suffixes(): Set<string> {
  const all = new Set<string>()
  for (const file of tracked()) {
    for (const path of [file, file.endsWith('.hbs') ? file.slice(0, -4) : file]) {
      const parts = path.split('/')
      for (let i = 0; i < parts.length; i++) all.add(parts.slice(i).join('/'))
    }
  }
  return all
}

function documents(): string[] {
  const docs = readdirSync(join(ROOT, 'docs'))
    .filter((name) => name.endsWith('.md'))
    .map((name) => `docs/${name}`)
  return [...docs, 'CLAUDE.md']
}

function referencedPaths(doc: string): string[] {
  const text = readFileSync(join(ROOT, doc), 'utf8')
  const found = new Set<string>()
  for (const match of text.matchAll(/`([^`\n]+)`/g)) {
    const token = (match[1] as string).trim()
    if (token.includes(' ') || !token.includes('/')) continue
    if (!/\.[a-z]{1,7}$/.test(token)) continue
    if (token.includes('*') || token.includes('<')) continue
    if (/^(https?:|--|\$|#|\.\.\/)/.test(token)) continue
    // Another repository, named on purpose. SYNC_BACKLOG is mostly this.
    if (/^koras-(control-plane|saas-starter)\//.test(token)) continue
    found.add(token)
  }
  return [...found].sort()
}

describe('paths named in the documentation', () => {
  const known = suffixes()

  it('has documents to read and paths to check', () => {
    // A filter that quietly matched nothing would make every case below pass
    // for the wrong reason — the failure mode of a test that reads text.
    expect(documents().length).toBeGreaterThan(5)
    expect(documents().flatMap(referencedPaths).length).toBeGreaterThan(30)
  })

  it.each(documents())('all exist, in %s', (doc) => {
    const missing = referencedPaths(doc).filter(
      (path) => !known.has(path) && !(path in ABSENT_ON_PURPOSE) && !(path in MOVED),
    )

    expect(
      missing,
      `${doc} names these and nothing in the repository matches them. ` +
        'If a file moved, add it to MOVED rather than editing a dated passage: ' +
        'rewriting the path falsifies the record of what was true then.',
    ).toEqual([])
  })

  it('exempts only paths this repository really does not have', () => {
    for (const [path, reason] of Object.entries(ABSENT_ON_PURPOSE)) {
      expect(known.has(path), `${path} exists now, so "${reason}" is stale`).toBe(false)
    }
  })

  it('records a move only where the old path is gone and the new one is there', () => {
    for (const [was, now] of Object.entries(MOVED)) {
      expect(known.has(was), `${was} exists again; it is not a moved path`).toBe(false)
      expect(known.has(now), `${was} is recorded as moved to ${now}, which does not exist`).toBe(
        true,
      )
    }
  })
})
