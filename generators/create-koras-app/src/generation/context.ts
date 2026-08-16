import type { ProfileManifest, ProfileDefaults, ComponentSelections } from '../profiles/types.js'
import type { ProfileName } from '../profiles/loader.js'

export interface GenerationContext {
  projectName: string
  projectSlug: string
  profile: ProfileName
  manifest: ProfileManifest
  defaults: ProfileDefaults
  selections: ComponentSelections
  outputDir: string
  dryRun: boolean
  provision: boolean
}

export function buildContext(params: {
  projectName: string
  projectSlug: string
  profile: ProfileName
  manifest: ProfileManifest
  defaults: ProfileDefaults
  selections: ComponentSelections
  outputDir: string
  dryRun: boolean
  provision: boolean
}): GenerationContext {
  return { ...params }
}

export function contextToTemplateVars(ctx: GenerationContext): Record<string, unknown> {
  return {
    projectName: ctx.projectName,
    projectSlug: ctx.projectSlug,
    profile: ctx.profile,
    isProduct: ctx.profile === 'product',
    isControlPlane: ctx.profile === 'control-plane',
    selections: ctx.selections,
  }
}
