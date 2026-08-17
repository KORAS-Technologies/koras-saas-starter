import { join } from 'node:path'
import { parseArgs } from './args.js'
import { promptInteractive } from './interactive.js'
import { validateSlug, deriveSlug } from '../validation/slug.js'
import { validateProfile } from '../validation/profile.js'
import { checkDirectoryConflict } from '../validation/conflicts.js'
import { loadProfile, listProfiles } from '../profiles/index.js'
import type { ProfileName } from '../profiles/loader.js'
import {
  resolveSelections,
  validateSelections,
  applyComponentOverrides,
} from '../profiles/validator.js'
import { buildContext } from '../generation/context.js'
import { renderTemplate } from '../generation/engine.js'
import { writeFiles, printDryRunManifest } from '../generation/writer.js'
import { provision } from '../terraform/runner.js'

const HELP_TEXT = `
create-koras-app — KORAS Application Factory

USAGE:
  pnpm create-koras-app [project] [options]

ARGUMENTS:
  project                    Project name

OPTIONS:
  --profile <profile>        Generator profile (required in non-interactive mode)
  --with <components>        Enable optional components (comma-separated)
  --without <components>     Disable optional components (comma-separated)
  --provision                Provision infrastructure via Terraform
  --dry-run                  Preview generation without writing files
  --output-dir <path>        Output parent directory (default: current directory)
  --no-interactive           Disable interactive prompts
  --list-profiles            List available profiles and exit
  --help                     Show this help message

EXAMPLES:
  pnpm create-koras-app
  pnpm create-koras-app docoris --profile product
  pnpm create-koras-app docoris --profile product --provision
  pnpm create-koras-app docoris --profile product --dry-run
  pnpm create-koras-app docoris --profile product --with marketing,ai_gateway
  pnpm create-koras-app koras-control-plane --profile control-plane
  pnpm create-koras-app koras-control-plane --profile control-plane --provision
`.trim()

function printListProfiles(): void {
  console.log('\nAvailable profiles:\n')
  const descriptions: Record<string, string> = {
    product: 'Standard KORAS SaaS product — web, admin, API, worker',
    'control-plane': 'KORAS Control Plane — platform provisioning authority',
  }
  for (const name of listProfiles()) {
    console.log(`  ${name.padEnd(20)} ${descriptions[name] ?? ''}`)
  }
  console.log()
}

function fail(message: string): never {
  console.error(`\nERROR: ${message}\n`)
  process.exit(1)
}

export async function run(argv: string[] = process.argv): Promise<void> {
  const args = parseArgs(argv)

  if (args.help) {
    console.log(HELP_TEXT)
    process.exit(0)
  }

  if (args.listProfiles) {
    printListProfiles()
    process.exit(0)
  }

  // ── Resolve project name, slug, and profile ────────────────────────────────

  let projectName: string
  let projectSlug: string
  let profileName: string
  let interactiveSelectionOverrides: import('../profiles/types.js').ComponentSelections | undefined

  const needsInteractive = !args.project || !args.profile

  if (needsInteractive && args.noInteractive) {
    const missing = []
    if (!args.project) missing.push('project name')
    if (!args.profile) missing.push('--profile')
    fail(
      `${missing.join(' and ')} is required in non-interactive mode.\n` +
        '  Example: pnpm create-koras-app myapp --profile product',
    )
  }

  if (needsInteractive) {
    const answers = await promptInteractive(args.project, args.profile)
    projectName = answers.projectName
    projectSlug = answers.projectSlug
    profileName = answers.profile
    interactiveSelectionOverrides = answers.selections as import('../profiles/types.js').ComponentSelections | undefined
  } else {
    projectName = args.project!
    projectSlug = deriveSlug(projectName)
    profileName = args.profile!
  }

  // ── Validate ───────────────────────────────────────────────────────────────

  const slugCheck = validateSlug(projectSlug)
  if (!slugCheck.valid) {
    const suggestion = slugCheck.suggestion ? `\n  Suggestion: ${slugCheck.suggestion}` : ''
    fail(`Invalid slug "${projectSlug}"\n  ${slugCheck.error}${suggestion}`)
  }

  const profileCheck = validateProfile(profileName)
  if (!profileCheck.valid) {
    fail(profileCheck.error!)
  }

  const dirCheck = checkDirectoryConflict(args.outputDir, projectSlug)
  if (dirCheck.conflict) {
    fail(dirCheck.message!)
  }

  // ── Load profile and resolve selections ────────────────────────────────────

  const { manifest, defaults } = loadProfile(profileName as ProfileName)
  const selections = resolveSelections(manifest, defaults)

  // Interactive answers first, then explicit --with/--without flags (flags win).
  if (interactiveSelectionOverrides) {
    Object.assign(selections.applications, interactiveSelectionOverrides.applications ?? {})
    Object.assign(selections.services, interactiveSelectionOverrides.services ?? {})
    Object.assign(selections.capabilities, interactiveSelectionOverrides.capabilities ?? {})
  }

  try {
    applyComponentOverrides(manifest, selections, { with: args.with, without: args.without })
    validateSelections(manifest, selections)
  } catch (err) {
    fail(err instanceof Error ? err.message : String(err))
  }

  // ── Build context ──────────────────────────────────────────────────────────

  const ctx = buildContext({
    projectName,
    projectSlug,
    profile: profileName as ProfileName,
    manifest,
    defaults,
    selections,
    outputDir: args.outputDir,
    dryRun: args.dryRun,
    provision: args.provision,
  })

  // ── Render template ────────────────────────────────────────────────────────

  const files = renderTemplate(ctx)

  if (ctx.dryRun && !ctx.provision) {
    printDryRunManifest(ctx, files)
    return
  }

  // ── Write files ────────────────────────────────────────────────────────────
  //
  // `--provision --dry-run` still writes the project: Terraform can only plan a
  // configuration that exists on disk. The dry run applies to infrastructure —
  // the run stops after `terraform plan`.

  if (ctx.dryRun && ctx.provision) {
    printDryRunManifest(ctx, files)
    console.log('\n--provision --dry-run: writing the project so Terraform can plan it.')
  }

  const writeCtx = ctx.dryRun ? { ...ctx, dryRun: false } : ctx
  const result = writeFiles(writeCtx, files)

  console.log(`\n✓ Generated ${result.filesWritten} files in ${projectSlug}/`)

  if (!ctx.provision) {
    console.log(`\nNext steps:`)
    console.log(`  cd ${projectSlug}`)
    console.log(`  make bootstrap`)
    console.log(`  make dev`)
    return
  }

  // ── Provision infrastructure ───────────────────────────────────────────────

  const outcome = await provision(ctx, {
    dryRun: ctx.dryRun,
    projectRoot: join(args.outputDir, projectSlug),
  })

  switch (outcome.status) {
    case 'applied':
      console.log('\n✓ Infrastructure provisioned.')
      console.log(`\nNext steps:`)
      console.log(`  cd ${projectSlug}`)
      console.log(`  make bootstrap`)
      break
    case 'planned':
      console.log(`\nThe project is generated in ${projectSlug}/. No infrastructure was created.`)
      break
    case 'declined':
      console.log(`\nThe project is generated in ${projectSlug}/. No infrastructure was created.`)
      console.log('Review the plan and re-run with --provision when ready.')
      break
    case 'missing-inputs':
      // preflight already printed the full list of what is missing
      process.exitCode = 1
      break
    default:
      console.error(`\nProvisioning failed at: ${outcome.status}`)
      console.error(`The project is generated in ${projectSlug}/ — Terraform can be re-run there.`)
      process.exitCode = 1
  }
}
