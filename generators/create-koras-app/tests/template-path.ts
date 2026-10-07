import { existsSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Where a template file actually lives.
 *
 * A profile is rendered from two layers -- `profiles/_shared/template/` and
 * `profiles/<profile>/template/` -- so a test that wants to read a template by
 * path has to look in both. Several read the profile path directly, which was
 * correct until the shared layer existed and then failed with ENOENT on files
 * that had simply moved. The generated output was unchanged; only the source
 * location was.
 *
 * Profile first, mirroring the engine: a profile that ships its own copy of a
 * shared path overrides it, and a test should see what generation would use.
 */
const PROFILES = join(__dirname, '..', '..', '..', 'profiles')

export function templatePath(profile: string, ...segments: string[]): string {
  const own = join(PROFILES, profile, 'template', ...segments)
  if (existsSync(own)) return own

  const shared = join(PROFILES, '_shared', 'template', ...segments)
  if (existsSync(shared)) return shared

  // A file the capability renders is carried as `<path>.hbs`. A test that names the output path
  // reads the template text, which holds both branches of each conditional; the assertions that
  // are about one mode render the product instead.
  const rendered = [own, shared].find((candidate) => existsSync(`${candidate}.hbs`))
  if (rendered !== undefined) return `${rendered}.hbs`

  throw new Error(
    `No template at ${segments.join('/')} for profile "${profile}".\n` +
      `  Looked in profiles/${profile}/template/ and profiles/_shared/template/.`,
  )
}
