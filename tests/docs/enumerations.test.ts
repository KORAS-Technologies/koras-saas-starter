import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { RESOURCE_KINDS } from '../../tooling/koras-cli/src/teardown/guards.js'

/**
 * Lists in the documentation, checked against the thing they list.
 *
 * Nearly every defect found in the week this was written came from an
 * enumeration written out by hand and then not updated: teardown knew seven
 * resource kinds where a provision creates eight, the test guarding that
 * asserted a second hand-written list with the same omission, and
 * INFRASTRUCTURE_PLAN said "all seven modules" beside a table of seven where
 * the directory held eight. Upstash and Cloudflare are the two that get left
 * off, and each of them outlived an estate as a result.
 *
 * The pattern is not carelessness. A list is correct when written and has no
 * way of noticing that the world moved; nothing fails, and the reader has no
 * reason to count. So each list here is compared against a source that cannot
 * drift from reality -- the modules directory, or the array the CLI itself
 * dispatches on.
 *
 * Deliberately not extended to the credential and prompt tables. Those map to
 * values with no runtime source, so a test would be a third copy of the same
 * list rather than a check of it.
 */

const ROOT = join(__dirname, '..', '..')

function read(doc: string): string {
  return readFileSync(join(ROOT, doc), 'utf8')
}

/** Terraform modules, excluding the one that calls the others. */
function modules(): string[] {
  return readdirSync(join(ROOT, 'infrastructure', 'terraform', 'modules'))
    .filter((name) => name !== 'project-bootstrap')
    .sort()
}

describe('the Terraform modules INFRASTRUCTURE_PLAN lists', () => {
  const doc = read('docs/INFRASTRUCTURE_PLAN.md')
  const found = modules()

  it('has modules to check', () => {
    // A directory read that returned nothing would make everything below pass.
    expect(found.length).toBeGreaterThan(5)
  })

  it.each(modules())('%s has a row in the table', (name) => {
    expect(doc, `no table row naming modules/${name}`).toContain(`\`modules/${name}\``)
  })

  it.each(modules())('%s has a section of its own', (name) => {
    expect(doc, `no "### \`modules/${name}\`" section`).toContain(`### \`modules/${name}\``)
  })

  it.each(modules())('%s appears in the directory tree', (name) => {
    expect(doc, `not in the directory tree`).toMatch(new RegExp(`[├└]──\\s+${name}/`))
  })

  it('counts them correctly in its own prose', () => {
    // "The orchestration module calls all seven modules" sat above a table of
    // seven while the directory held eight, and read as a statement of
    // completeness rather than a number anybody would check.
    const words = [
      'zero', 'one', 'two', 'three', 'four', 'five', 'six',
      'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
    ]
    const claim = /orchestration module calls all (\w+) modules/.exec(doc)
    expect(claim, 'the "calls all N modules" sentence is gone; update this test').not.toBeNull()
    expect(claim?.[1], `there are ${String(found.length)} modules`).toBe(words[found.length])
  })
})

describe('the resource kinds PROVISIONING_RUNBOOK lists', () => {
  const doc = read('docs/PROVISIONING_RUNBOOK.md')

  it('has kinds to check', () => {
    expect(RESOURCE_KINDS.length).toBeGreaterThan(5)
  })

  it.each(RESOURCE_KINDS)('%s is in the teardown table', (kind) => {
    // Compared against the array the CLI dispatches on, not a copy of it. This
    // is the check that would have named Cloudflare: it was a kind the command
    // could not delete and the runbook did not mention, and the count of what
    // the inventory held could not reveal either.
    expect(doc, `step 1's table does not mention ${kind}`).toContain(`\`${kind}\``)
  })
})

/**
 * Named in §2 despite living in §3.
 *
 * An exemption is a claim as well, so it is asserted rather than assumed: if
 * GitHub gains a §2 section this fails, and the reason recorded here has stopped
 * being true.
 */
const ISOLATION_EXEMPT: Record<string, string> = {}

describe('the providers ENVIRONMENT_STRATEGY isolates per environment', () => {
  const doc = read('docs/ENVIRONMENT_STRATEGY.md')
  const isolation = doc.slice(
    doc.indexOf('## 2. Environment Isolation'),
    doc.indexOf('## 3. GitHub Branch Configuration'),
  )

  /** `modules/fly` is written "Fly.io"; the rest match their heading directly. */
  const HEADINGS: Record<string, string> = { fly: 'Fly.io' }

  it('found the section', () => {
    expect(isolation.length).toBeGreaterThan(500)
  })

  it.each(modules())('%s has a heading', (name) => {
    if (name in ISOLATION_EXEMPT) return
    const heading = HEADINGS[name] ?? name
    const pattern = new RegExp(`^### ${heading}\\s*$`, 'im')
    expect(
      pattern.test(isolation),
      `section 2 has no "### ${heading}". Every provider a provision writes to ` +
        'belongs here; Upstash and Cloudflare were absent from this document ' +
        'while being created on every run.',
    ).toBe(true)
  })

  it('exempts only providers that really have no section', () => {
    for (const [name, reason] of Object.entries(ISOLATION_EXEMPT)) {
      const heading = HEADINGS[name] ?? name
      expect(
        new RegExp(`^### ${heading}\\s*$`, 'im').test(isolation),
        `${heading} has a section now, so "${reason}" is stale`,
      ).toBe(false)
    }
  })
})
