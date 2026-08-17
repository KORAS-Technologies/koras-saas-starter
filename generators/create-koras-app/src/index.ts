export { run } from './cli/index.js'
export { loadProfile, listProfiles, isValidProfile } from './profiles/index.js'
export { validateSlug, deriveSlug } from './validation/slug.js'
export { validateProfile } from './validation/profile.js'
export { checkDirectoryConflict } from './validation/conflicts.js'
export { renderTemplate } from './generation/engine.js'
export { writeFiles, printDryRunManifest } from './generation/writer.js'
export { buildContext, contextToTemplateVars } from './generation/context.js'
export type { GenerationContext } from './generation/context.js'
export type { RenderedFile } from './generation/engine.js'
export { provision, shouldUseDoppler, summarisePlan } from './terraform/runner.js'
export { confirmApply } from './terraform/approval.js'
export {
  preflightInputs,
  formatMissingInputs,
  generatorProvidedInputs,
  terraformDirectory,
  PROVIDER_CREDENTIALS,
  SECRET_VARIABLES,
  ACCOUNT_VARIABLES,
} from './terraform/inputs.js'
export { parseTerraformOutputs, groupByEnvironment, formatOutputs } from './terraform/outputs.js'
export type { ProvisionResult, ProvisionStatus, CommandExecutor } from './terraform/runner.js'
export type { ProvisionOutputs, EnvironmentReferences } from './terraform/outputs.js'
