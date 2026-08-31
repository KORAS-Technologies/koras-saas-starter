import { describe, it, expect } from 'vitest'
import { existsSync, readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

/**
 * The two profiles do not hold two copies of the same file.
 *
 * This used to be a hand-maintained list of 112 paths that existed twice, with
 * an assertion that the two copies were byte-identical. That was a guard rather
 * than a fix, and its own comment said so: the fix was a `profiles/_shared/`
 * tree, which `shared_assets` could not carry because it copies verbatim and
 * unconditionally.
 *
 * That tree exists now and holds all 112, so the assertion inverts. Rather than
 * listing what must stay identical, this asserts structurally that no path
 * exists in both profile templates at once. A list has to be remembered; an
 * invariant does not, and this one catches a file duplicated tomorrow that no
 * list would have known to mention.
 *
 * Deliberate divergence is still available and still visible. A profile that
 * ships its own copy of a path in `_shared/` overrides it -- but the file then
 * exists in `_shared` and in one profile, never in both, so this still holds.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')
const SHARED_LAYER = join(PROFILES, '_shared', 'template')

function filesUnder(root: string): string[] {
  if (!existsSync(root)) return []
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) walk(full)
      else out.push(relative(root, full).split(sep).join('/'))
    }
  }
  walk(root)
  return out
}


/**
 * Line endings are normalised, and so is trailing whitespace.
 *
 * CRLF because a checkout on Windows carries it. The trailing trim is the
 * second lesson: five Python package markers sat in both profiles for months,
 * empty in one and holding a single newline in the other, and this test passed
 * on every run because two bytes is not zero bytes. A duplicate that differs
 * only in whether the file ends with a newline is still a duplicate, and it is
 * the *easiest* kind to create -- an editor does it without being asked.
 */
function read(profile: string, file: string): string {
  const CR = String.fromCharCode(13)
  return readFileSync(join(PROFILES, profile, 'template', file), 'utf8')
    .split(CR)
    .join('')
    .replace(/\s+$/gm, '')
    .trim()
}

const productFiles = filesUnder(join(PROFILES, 'product', 'template'))
const controlPlaneFiles = filesUnder(join(PROFILES, 'control-plane', 'template'))
const sharedFiles = filesUnder(SHARED_LAYER)

describe('the two profiles do not drift apart', () => {
  it('holds no byte-identical copy of the same path in both profiles', () => {
    // The class of defect this repository kept producing: a fix lands in one
    // profile, the other keeps the old version, and a review of either
    // repository shows nothing.
    //
    // A path in both profiles is fine when the contents genuinely differ --
    // apps/admin/next.config.ts.hbs transpiles a different set of packages per
    // profile, and there is no single version to share. Two *identical* copies
    // are the defect: nothing distinguishes them, so nothing keeps them in step
    // except somebody remembering.
    const duplicated = productFiles
      .filter((file) => controlPlaneFiles.includes(file))
      .filter((file) => read('product', file) === read('control-plane', file))
    expect(duplicated).toEqual([])
  })

  it('is not vacuous -- both profiles do hold files of their own', () => {
    expect(productFiles.length).toBeGreaterThan(0)
    expect(controlPlaneFiles.length).toBeGreaterThan(0)
  })
})

describe('the shared template layer is single-sourced', () => {
  /**
   * A shared path may be overridden by one profile, and never by both.
   *
   * This used to assert that a shared path existed in neither profile, which
   * was stricter than the invariant above it and stricter than the paragraph at
   * the top of this file describing it -- that paragraph has always said
   * divergence stays available, with the file existing "in `_shared` and in one
   * profile, never in both".
   *
   * The stricter reading forbade the override the engine is built to support:
   * `renderTemplate` walks `_shared` first and the profile second, keyed by
   * output path, precisely so a profile can ship its own version of a shared
   * file. `packages/ui` is the case that exposed it. The product profile turns
   * that package into a real design system -- React components, a Tailwind
   * theme, a JSX tsconfig -- while the Control Plane keeps the two-line stub,
   * and there is no single version for both.
   *
   * What must not happen is *two* overrides, which is the shared layer being
   * bypassed rather than extended.
   */
  it.each(sharedFiles)('%s is overridden by at most one profile', (file) => {
    const overriding = ['product', 'control-plane'].filter((profile) =>
      existsSync(join(PROFILES, profile, 'template', file)),
    )
    expect(
      overriding,
      `${file} is overridden by both profiles, so the shared copy reaches nobody`,
    ).not.toEqual(['product', 'control-plane'])
  })

  /**
   * An override that is identical to what it overrides is a duplicate wearing a
   * different hat: two files to keep in step, and nothing to say which is
   * authoritative.
   */
  it.each(sharedFiles)('%s is not overridden by an identical copy', (file) => {
    const shared = readFileSync(join(SHARED_LAYER, file), 'utf8')
      .split(String.fromCharCode(13))
      .join('')
      .replace(/\s+$/gm, '')
      .trim()
    for (const profile of ['product', 'control-plane']) {
      if (!existsSync(join(PROFILES, profile, 'template', file))) continue
      expect(read(profile, file), `${profile} overrides ${file} with the same content`).not.toBe(
        shared,
      )
    }
  })

  it('carries what the duplicated list used to', () => {
    // Guards the guard. The list this replaced held 112 paths; emptying the
    // shared tree would leave every assertion above passing while checking
    // nothing.
    expect(sharedFiles.length).toBeGreaterThanOrEqual(112)
  })
})
