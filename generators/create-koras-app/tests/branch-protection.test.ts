import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Branch protection asks for checks the CI actually produces.
 *
 * GitHub names a check `<workflow name> / <job name>`. Nothing connects the
 * module's `contexts` list to the workflow the templates ship, so renaming a job
 * -- or renaming the workflow -- leaves a required check that can never report.
 * A branch protected by a check nothing produces does not fail loudly: pull
 * requests simply stop being mergeable, and the reason is a string mismatch
 * nobody is looking at.
 *
 * The reverse is what was actually wrong. `contexts` named two of the five jobs,
 * so a pull request with failing tests, or a secret in its history, could merge
 * to main -- the two checks most worth blocking on were the two not required.
 */

const ROOT = join(__dirname, '..', '..', '..')
const PROFILES = ['product', 'control-plane'] as const

/**
 * Line endings are normalised first. A checkout on Windows carries CRLF, and a
 * pattern spanning two lines then matches nothing -- which would leave every
 * assertion here passing over an empty set. That is the failure the vacuity
 * check below exists for, and it caught exactly this.
 */
function read(...parts: string[]): string {
  const CR = String.fromCharCode(13)
  return readFileSync(join(ROOT, ...parts), 'utf8').split(CR).join('')
}

function workflowContexts(profile: string): string[] {
  const source = read('profiles', profile, 'template', '.github', 'workflows', 'ci.yml')
  const workflow = /^name:\s*(.+)$/m.exec(source)?.[1]?.trim()
  const jobs = [...source.matchAll(/^ {2}[a-z0-9-]+:\n {4}name:\s*(.+)$/gm)].map((m) =>
    m[1].trim(),
  )
  return jobs.map((job) => `${workflow} / ${job}`).sort()
}

function requiredContexts(): string[] {
  const source = read('infrastructure', 'terraform', 'modules', 'github', 'main.tf')
  const block = source.slice(source.indexOf('contexts = ['))
  const list = block.slice(0, block.indexOf(']'))
  return [...list.matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort()
}

describe('required status checks', () => {
  it.each(PROFILES)('%s: every required check is a job the CI defines', (profile) => {
    const produced = new Set(workflowContexts(profile))
    const unproducible = requiredContexts().filter((c) => !produced.has(c))
    expect(unproducible, 'these can never report, so nothing would ever merge').toEqual([])
  })

  it.each(PROFILES)('%s: every job the CI defines is required', (profile) => {
    // The direction that was wrong. Lint and build were required; the secret
    // scan and both test jobs were not.
    const required = new Set(requiredContexts())
    expect(workflowContexts(profile).filter((c) => !required.has(c))).toEqual([])
  })

  it('is not vacuous', () => {
    // Both assertions above pass over an empty set. If the contexts list were
    // emptied, or the workflow parser stopped matching, this suite would report
    // a protection that requires nothing as correct.
    expect(requiredContexts().length).toBeGreaterThanOrEqual(5)
    expect(workflowContexts('product').length).toBeGreaterThanOrEqual(5)
  })

  it('requires checks only where a pull request is required', () => {
    // A direct push cannot satisfy a status check: the checks run against a
    // commit that does not exist on the server until the push completes. On
    // `develop`, which permits direct pushes by design, requiring them made
    // every push a recorded bypass -- and a protection bypassed on every use is
    // a line in an audit log people learn to scroll past.
    const source = read('infrastructure', 'terraform', 'modules', 'github', 'main.tf')
    expect(source).toMatch(/dynamic "required_status_checks"[\s\S]{0,120}each\.value\.require_pr/)
    expect(source).toMatch(/develop\s*=\s*\{[^}]*require_pr\s*=\s*false/)
  })
})
