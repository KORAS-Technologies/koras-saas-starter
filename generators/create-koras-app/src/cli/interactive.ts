import * as p from '@clack/prompts'
import { listProfiles, loadProfile } from '../profiles/index.js'
import type { ProfileName } from '../profiles/loader.js'
import { validateSlug, deriveSlug } from '../validation/slug.js'
import type { ComponentSelections } from '../profiles/types.js'

export interface InteractiveAnswers {
  projectName: string
  projectSlug: string
  profile: string
  selections?: Partial<ComponentSelections>
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
    selections: await promptOptionalComponents(String(profile) as ProfileName),
  }
}

async function promptOptionalComponents(
  profile: ProfileName,
): Promise<Partial<ComponentSelections>> {
  const { manifest } = loadProfile(profile)

  const optionalApps = Object.entries(manifest.applications).filter(([, v]) => !v.required)
  const optionalServices = Object.entries(manifest.services).filter(([, v]) => !v.required)

  // control-plane has no optional components — skip prompts
  if (optionalApps.length === 0 && optionalServices.length === 0) {
    return {}
  }

  const applications: Record<string, boolean> = {}
  const services: Record<string, boolean> = {}

  if (optionalApps.length > 0) {
    const selected = await p.multiselect({
      message: 'Optional applications:',
      options: optionalApps.map(([name, app]) => ({
        value: name,
        label: name,
        hint: app.description,
      })),
      required: false,
    })
    if (p.isCancel(selected)) { p.cancel('Cancelled.'); process.exit(0) }
    for (const [name] of optionalApps) {
      applications[name] = (selected as string[]).includes(name)
    }
  }

  if (optionalServices.length > 0) {
    const selected = await p.multiselect({
      message: 'Optional services:',
      options: optionalServices.map(([name, svc]) => ({
        value: name,
        label: name,
        hint: svc.description,
      })),
      required: false,
    })
    if (p.isCancel(selected)) { p.cancel('Cancelled.'); process.exit(0) }
    for (const [name] of optionalServices) {
      services[name] = (selected as string[]).includes(name)
    }
  }

  return { applications, services, capabilities: {} }
}
