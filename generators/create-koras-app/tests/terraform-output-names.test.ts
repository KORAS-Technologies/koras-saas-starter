import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Every output the parser reads must be one the templates emit.
 *
 * `parseTerraformOutputs` looks each value up by name and returns an empty map
 * when it is absent, because a provision that genuinely created no Vercel
 * projects should not throw. That tolerance is right and it is indistinguishable
 * from a typo, so a name nobody emits reads as "there were none of those".
 *
 * This is not hypothetical. `redis_database_ids` was read here and exported by
 * nothing, so `redisDatabaseIds` was always `{}`, Upstash never entered the
 * teardown inventory, and a run reported "26 deletable, 0 retained" while four
 * billing databases stayed alive (R-040). Nothing failed. Nothing could: the
 * only signal was a number that looked plausible.
 *
 * So the two sides are compared directly, by reading the names out of both
 * rather than by listing them here -- a list would be a third place to forget.
 */

const ROOT = join(__dirname, '..', '..', '..')
const PROFILES = ['product', 'control-plane'] as const

/**
 * Outputs one profile emits and the other has no equivalent for.
 *
 * The rule below is that a name nobody emits parses as empty and looks
 * identical to a typo. That still holds -- each entry here is asserted to be
 * emitted by *some* profile, so a misspelling fails as loudly as before. What
 * is relaxed is the demand that both emit it, which is wrong for a value only
 * one profile has.
 *
 * `app_urls` is where a customer of a product signs in. The Control Plane has
 * no such thing: its customer surface is the portal, emitted as `portal_urls`,
 * and it registers itself as a product nowhere -- refused four independent
 * ways. Emitting `app_urls` there to satisfy a test would put two spellings of
 * one hostname in the estate, which is precisely how a redirect URI stops
 * matching the domain it was issued for.
 */
const PROFILE_SPECIFIC: Record<string, readonly string[]> = {
  'control-plane': ['app_urls'],
}

function parserReads(): string[] {
  const source = readFileSync(join(__dirname, '..', 'src', 'terraform', 'outputs.ts'), 'utf8')
  // asStringMap('x'), asStringList('x'), read('x') -- whatever the helper, the
  // argument is the output name.
  const names = new Set<string>()
  for (const match of source.matchAll(/\b(?:asStringMap|asStringList|read)\('([a-z0-9_]+)'\)/g)) {
    names.add(match[1] as string)
  }
  return [...names].sort()
}

function templateEmits(profile: string): string[] {
  const source = readFileSync(
    join(ROOT, 'profiles', profile, 'template', 'infrastructure', 'terraform', 'main.tf.hbs'),
    'utf8',
  )
  const names = new Set<string>()
  for (const match of source.matchAll(/^output "([a-z0-9_]+)"/gm)) names.add(match[1] as string)
  return [...names].sort()
}

describe('the Terraform outputs the parser reads', () => {
  it('finds names to check, in both directions', () => {
    // A regex that matched nothing would make every assertion below vacuous,
    // which is the failure mode of a test that reads source rather than calls
    // it.
    expect(parserReads().length).toBeGreaterThan(5)
    for (const profile of PROFILES) expect(templateEmits(profile).length).toBeGreaterThan(5)
  })

  it.each(PROFILES)('is emitted by the %s template', (profile) => {
    const emitted = new Set(templateEmits(profile))
    const exempt = new Set(PROFILE_SPECIFIC[profile] ?? [])
    const missing = parserReads().filter((name) => !emitted.has(name) && !exempt.has(name))

    expect(
      missing,
      `parseTerraformOutputs reads these, and the ${profile} root emits none of them, ` +
        'so each one silently parses as empty',
    ).toEqual([])
  })

  it('exempts nothing that no profile emits', () => {
    // The guard on the exemption. A typo added to PROFILE_SPECIFIC would
    // otherwise be excused everywhere and parse as empty in silence, which is
    // the exact failure this file exists to catch.
    const anywhere = new Set(PROFILES.flatMap((profile) => templateEmits(profile)))
    for (const [profile, names] of Object.entries(PROFILE_SPECIFIC)) {
      for (const name of names) {
        expect(
          anywhere.has(name),
          `${name} is exempted for ${profile} but no profile emits it at all`,
        ).toBe(true)
      }
    }
  })

  it('reads the organization alongside every project id', () => {
    // Paired on purpose: a ZITADEL project id cannot be deleted without knowing
    // the organization it lives in, and an estate with two organizations
    // answers 404 -- "already gone" -- for a delete aimed at the wrong one.
    const read = parserReads()
    expect(read).toContain('zitadel_project_ids')
    expect(read).toContain('zitadel_resolved_org_ids')
    expect(read).toContain('zitadel_domains')
  })
})
