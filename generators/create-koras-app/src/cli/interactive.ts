import * as p from '@clack/prompts'
import { listProfiles } from '../profiles/index.js'
import { validateSlug, deriveSlug } from '../validation/slug.js'

export interface InteractiveAnswers {
  projectName: string
  projectSlug: string
  profile: string
}

export async function promptInteractive(
  initialProject?: string,
  initialProfile?: string,
): Promise<InteractiveAnswers> {
  p.intro('KORAS Application Factory')

  const projectName = initialProject
    ? initialProject
    : await p.text({
        message: 'Project name:',
        validate: (v) => (v.trim().length < 2 ? 'Name must be at least 2 characters.' : undefined),
      })

  if (p.isCancel(projectName)) {
    p.cancel('Cancelled.')
    process.exit(0)
  }

  const derivedSlug = deriveSlug(String(projectName))
  const projectSlug = await p.text({
    message: 'Project slug:',
    initialValue: derivedSlug,
    validate: (v) => {
      const result = validateSlug(v)
      return result.valid ? undefined : result.error
    },
  })

  if (p.isCancel(projectSlug)) {
    p.cancel('Cancelled.')
    process.exit(0)
  }

  const profile = initialProfile
    ? initialProfile
    : await p.select({
        message: 'Project profile:',
        options: listProfiles().map((name) => ({ value: name, label: name })),
      })

  if (p.isCancel(profile)) {
    p.cancel('Cancelled.')
    process.exit(0)
  }

  return {
    projectName: String(projectName),
    projectSlug: String(projectSlug),
    profile: String(profile),
  }
}
