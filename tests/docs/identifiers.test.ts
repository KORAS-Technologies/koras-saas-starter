import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * An identifier named in a document has to exist in the code.
 *
 * The third mechanical class in R-042, after paths and lists. A document
 * described `environments/dev.tfvars` files configured through a
 * `vercel_target`; neither has existed at any point. Another described a
 * `terraform.tfvars.json` written to a temporary directory and deleted, which
 * is not how any of it works. Both read as descriptions of the system and were
 * descriptions of a plan replaced before it was built.
 *
 * Measured when written: 683 identifier-shaped mentions across the documents,
 * of which 12 resolved to nothing and 8 of those were legitimate. A check that
 * finds 4 real problems in 683 mentions is worth having; one that flagged 100
 * would be switched off, which is why the filters below are narrow rather than
 * clever.
 *
 * What counts as an identifier: SCREAMING_SNAKE_CASE, and lower_snake_case with
 * at least one underscore. A lowercase word without one is prose --
 * `microservice` is not a symbol -- and matching it would flag English.
 */

const ROOT = join(__dirname, '..', '..')

/**
 * Named in a document, absent from the code, and correctly so.
 *
 * Each is asserted absent below. An exemption is a claim too, and one that
 * quietly stops being true is the same defect this file exists to catch.
 */
const ABSENT_ON_PURPOSE: Record<string, string> = {
  ZITADEL_DEV_SERVICE_TOKEN: 'built at runtime from the environment name',
  ZITADEL_TEST_SERVICE_TOKEN: 'built at runtime from the environment name',
  ZITADEL_PROD_SERVICE_TOKEN: 'built at runtime from the environment name',
  STATUS_DLL_INIT_FAILED: 'a Windows error code, quoted in a failure table',
  delete_repo: 'a GitHub *classic* token scope, named in R-036 to say it is the wrong one',
  null_resource: 'a Terraform concept named in a dated account of what was tried',
  attach_branch_domains: 'a removed resource, named in the entry recording its removal',
  storage_buckets: 'named in SYNC_BACKLOG as something the storage module does not create',
  vercel_target: 'named in ENVIRONMENT_STRATEGY to say it has never existed',
  // A shell variable in NEW_PRODUCT_WALKTHROUGH's curl examples, not a setting
  // the platform has. The credential it holds is a ZITADEL id token copied out
  // of the console's cookie, which no code here names -- so it must stay absent,
  // and a name like this appearing in the code would mean somebody had started
  // storing a staff token.
  STAFF_TOKEN: "a shell variable in a worked example; the platform has no such setting",
  // The Control Plane's registry tables. REGISTRATION_LIFECYCLE names them
  // because the safety of a single-environment re-registration rests on which
  // of them prune and which do not -- read out of that repository rather than
  // assumed. A product repository must never have them, so asserting their
  // absence here is worth something on its own.
  product_environments: 'a Control Plane registry table; no product repository has one',
  product_services: 'a Control Plane registry table; no product repository has one',
  infrastructure_references: 'a Control Plane registry table; no product repository has one',
  // The commercial catalogue's join table, named in FOLLOW_UPS because the size
  // of the authoring gap is measured in rows of it. Same rule as the three
  // above: it is the Control Plane's, and a product that had one would be
  // deciding its own entitlements.
  plan_entitlements: 'a Control Plane catalogue table; no product repository has one',
}

function tracked(): string[] {
  return execFileSync('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .filter(Boolean)
}

/**
 * Everything that is not prose: the code, configuration and templates.
 *
 * This file alone is excluded, and only because its exemption map spells out
 * the identifiers it asserts are absent -- scanning itself found
 * `ZITADEL_DEV_SERVICE_TOKEN` in the code and called the exemption stale.
 *
 * Excluding the whole of `tests/docs/` was the first attempt and was wrong:
 * `ABSENT_ON_PURPOSE` and `MOVED` are real symbols in the sibling test, named
 * in R-042, and hiding them made two true references look invented. The
 * exclusion has to be exactly as wide as the self-reference.
 */
function codeText(): string {
  let all = ''
  for (const file of tracked()) {
    if (file.endsWith('.md')) continue
    if (file === 'tests/docs/identifiers.test.ts') continue
    try {
      all += readFileSync(join(ROOT, file), 'utf8')
    } catch {
      // Binary, or gone since `git ls-files` ran. Neither carries identifiers.
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

const SCREAMING = /^[A-Z][A-Z0-9_]{4,}$/
const SNAKE = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/
/** A commit SHA is not an identifier, and several are quoted in dated entries. */
const HEX = /^[0-9a-f]{7,40}$/

function identifiers(doc: string): string[] {
  const text = readFileSync(join(ROOT, doc), 'utf8')
  const found = new Set<string>()
  for (const match of text.matchAll(/`([^`\n]+)`/g)) {
    const token = (match[1] as string).trim()
    if (HEX.test(token)) continue
    if (!SCREAMING.test(token) && !SNAKE.test(token)) continue
    found.add(token)
  }
  return [...found].sort()
}

describe('identifiers named in the documentation', () => {
  const code = codeText()

  it('finds identifiers to check', () => {
    // A filter matching nothing would make every case below pass silently --
    // the failure mode of a test that reads text rather than calling code.
    expect(documents().flatMap(identifiers).length).toBeGreaterThan(100)
  })

  it.each(documents())('all exist, in %s', (doc) => {
    const missing = identifiers(doc).filter(
      (name) => !(name in ABSENT_ON_PURPOSE) && !code.includes(name),
    )

    expect(
      missing,
      `${doc} names these and no file outside docs/ contains them. ` +
        'A document describing a plan that was replaced before it was built ' +
        'reads exactly like one describing the system.',
    ).toEqual([])
  })

  it('exempts only identifiers the code really does not contain', () => {
    for (const [name, reason] of Object.entries(ABSENT_ON_PURPOSE)) {
      expect(code.includes(name), `${name} exists now, so "${reason}" is stale`).toBe(false)
    }
  })
})
