import { join } from 'node:path'
import { existsSync } from 'node:fs'
import { parseArgs } from './args.js'
import { promptInteractive } from './interactive.js'
import { validateSlug, deriveSlug } from '../validation/slug.js'
import { validateProfile } from '../validation/profile.js'
import { checkDirectoryConflict } from '../validation/conflicts.js'
import { checkOutputDirectory } from '../validation/output-dir.js'
import { validateGeneratedProject } from '../validation/generated-project.js'
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
import { formatRefreshResult, refreshSharedAssets } from '../generation/refresh.js'
import { provision } from '../terraform/runner.js'
import { preflightInputs } from '../terraform/inputs.js'
import {
  dopplerUnavailableMessage,
  reexecUnderDoppler,
  resolveDopplerLocation,
  shouldReexecUnderDoppler,
} from '../terraform/doppler.js'
import { initAndPushToDevelop } from '../git.js'

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
  --provision-only           Provision an existing project; skips generation
  --refresh-modules          Re-copy the shared Terraform modules into an
                             existing project. Combine with --provision-only to
                             plan against the refreshed copy.
  --dry-run                  Preview generation without writing files
  --output-dir <path>        Output parent directory (default: current directory)
  --no-interactive           Disable interactive prompts
  --list-profiles            List available profiles and exit
  --help                     Show this help message

EXAMPLES:
  Generate only — no infrastructure is touched:
    pnpm create-koras-app docoris --profile product --output-dir ../output
    pnpm create-koras-app docoris --profile product --output-dir ../output --dry-run
    pnpm create-koras-app docoris --profile product --output-dir ../output \\
      --with marketing,ai_gateway
    pnpm create-koras-app koras-control-plane --profile control-plane --output-dir ../output

  Provision — credentials are pulled from Doppler automatically:
    pnpm create-koras-app docoris --profile product --provision --output-dir ../output

  Retry a run that failed partway — skips generation, keeps existing state:
    pnpm create-koras-app docoris --profile product --provision-only --output-dir ../output

  Pick up a module fixed in the starter since the project was generated:
    pnpm create-koras-app docoris --profile product --refresh-modules --output-dir ../output
    pnpm create-koras-app docoris --profile product --refresh-modules --provision-only \
      --output-dir ../output

  An outer \`doppler run\` is still honoured, and DOPPLER_PROJECT / DOPPLER_CONFIG
  override the profile's location for a one-off run.

Check the estate before provisioning: pnpm koras bootstrap:doctor
See PROVISIONING_RUNBOOK.md for prerequisites and failure recovery.
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

  // Generating into the starter repo itself is almost always a slip — the
  // default output directory is wherever you happen to be standing.
  const outputCheck = checkOutputDirectory(args.outputDir, args.outputDirExplicit)
  const existingProject = args.provisionOnly || args.refreshModules
  if (outputCheck.refused && !existingProject) {
    fail(outputCheck.message!)
  }

  const projectRoot = join(args.outputDir, projectSlug)

  if (existingProject) {
    // Retrying after a failed apply is routine, so this path deliberately
    // requires the directory the normal path refuses to overwrite.
    if (!existsSync(projectRoot)) {
      const flag = args.provisionOnly ? '--provision-only' : '--refresh-modules'
      fail(
        `No generated project at ${projectRoot}\n` +
          `  ${flag} operates on an existing project.\n` +
          `  Generate it first: pnpm create-koras-app ${projectSlug} --profile ${profileName}`,
      )
    }
  } else {
    const dirCheck = checkDirectoryConflict(args.outputDir, projectSlug)
    if (dirCheck.conflict) {
      fail(
        `${dirCheck.message!}\n` +
          '  To provision this existing project instead, use --provision-only.',
      )
    }
  }

  // ── Load profile and resolve selections ────────────────────────────────────

  const { manifest, defaults } = loadProfile(profileName as ProfileName)
  const selections = resolveSelections(manifest, defaults)

  // ── Credentials ────────────────────────────────────────────────────────────
  // Provisioning needs secrets that live in Doppler. Rather than making the
  // operator remember the wrapper, re-run this same command under `doppler run`
  // once the profile has told us where the credentials are. Done here, before
  // any work, so the child does the generating and provisioning exactly as if
  // it had been wrapped by hand.

  if (
    shouldReexecUnderDoppler({
      required: args.provision || args.provisionOnly,
      satisfied: preflightInputs().ok,
    })
  ) {
    const location = resolveDopplerLocation(defaults)
    if (location) {
      try {
        process.exit(await reexecUnderDoppler(location, process.argv))
      } catch {
        console.error(dopplerUnavailableMessage(location))
        process.exit(1)
      }
    }
  }

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

  // ── Provision an existing project ──────────────────────────────────────────

  // ── Refresh shared modules ─────────────────────────────────────────────────
  // Before provisioning, so the plan that follows reflects the refreshed code
  // rather than the copy the project was generated with.

  if (args.refreshModules) {
    console.log(formatRefreshResult(refreshSharedAssets(ctx, projectRoot)))
    if (!args.provisionOnly) return
  }

  if (args.provisionOnly) {
    console.log(`
Provisioning the existing project in ${projectSlug}/ — nothing regenerated.`)
    await runProvision(ctx, projectRoot, projectSlug, false)
    return
  }

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
    console.log(
      `\nNote: --provision --dry-run writes ${projectSlug}/ to disk — Terraform can only` +
        '\nplan a configuration that exists. No infrastructure is created.',
    )
    printDryRunManifest(ctx, files)
  }

  const writeCtx = ctx.dryRun ? { ...ctx, dryRun: false } : ctx
  const result = writeFiles(writeCtx, files)

  // ── Validate the generated repository ──────────────────────────────────────
  //
  // Read back from disk before anything downstream trusts it — and before
  // provisioning, which acts on the profile this manifest records.

  const projectCheck = validateGeneratedProject({
    projectRoot,
    expectedSlug: projectSlug,
    expectedProfile: profileName,
  })
  if (!projectCheck.valid) {
    fail(
      `Generated project failed validation.\n  ${projectCheck.error!}\n` +
        `  Nothing was provisioned. Inspect or delete ${projectSlug}/ and regenerate.`,
    )
  }

  console.log(`\n✓ Generated ${result.filesWritten} files in ${projectSlug}/`)

  if (!ctx.provision) {
    console.log(`\nNext steps:`)
    console.log(`  cd ${projectSlug}`)
    console.log(`  make bootstrap`)
    console.log(`  make dev`)
    return
  }

  // ── Provision infrastructure ───────────────────────────────────────────────

  await runProvision(ctx, projectRoot, projectSlug, true)
}

async function runProvision(
  ctx: import('../generation/context.js').GenerationContext,
  projectRoot: string,
  projectSlug: string,
  /**
   * Whether this run also generated the project.
   *
   * `--provision-only` operates on a project that already exists, and whose
   * repository was pushed the first time round. Running the git bootstrap
   * again would `pnpm install` into it and try to commit -- writing files into
   * a tree the operator owns, during what was asked to be an infrastructure
   * operation.
   */
  generated: boolean,
): Promise<void> {
  const outcome = await provision(ctx, { dryRun: ctx.dryRun, projectRoot })

  switch (outcome.status) {
    case 'applied': {
      console.log('\n✓ Infrastructure provisioned.')
      const repoFullName = outcome.outputs?.githubRepository
      if (repoFullName && !generated) {
        console.log(`
  Repository: https://github.com/${repoFullName}`)
        console.log('  --provision-only touches infrastructure only; nothing was committed.')
      }
      if (repoFullName && generated) {
        try {
          await initAndPushToDevelop({ projectRoot, repositoryFullName: repoFullName })
          console.log(`\n✓ Repository initialised and pushed to develop.`)
          console.log(`  Populate main/test/staging via PRs from develop.`)
        } catch (err) {
          console.warn(`\n⚠ Git initialisation failed: ${err instanceof Error ? err.message : String(err)}`)
          // These must mirror initAndPushToDevelop exactly. In particular the
          // update-ref graft onto origin/develop: without it the local branch
          // has no common ancestor with the repository Terraform created, the
          // push is rejected as non-fast-forward, and the only way through is a
          // force push that branch protection declines (GH006).
          console.warn(`  Run these steps manually in ${projectSlug}/:`)
          console.warn(`    pnpm install`)
          console.warn(`    git init -b develop`)
          console.warn(`    git remote add origin https://github.com/${repoFullName}.git`)
          console.warn(`    git fetch origin`)
          console.warn(`    git update-ref refs/heads/develop refs/remotes/origin/develop`)
          console.warn(`    git add . && git commit -m "chore: initial project generation"`)
          console.warn(`    git push origin develop`)
        }
      }
      console.log(`\nNext steps:`)
      console.log(`  cd ${projectSlug}`)
      console.log(`  make bootstrap`)
      break
    }
    case 'planned':
      console.log(`\nThe project is generated in ${projectSlug}/. No infrastructure was created.`)
      break
    case 'declined':
      console.log(`\nThe project is generated in ${projectSlug}/. No infrastructure was created.`)
      console.log(
        `Review the plan, then: pnpm create-koras-app ${projectSlug} ` +
          `--profile ${ctx.profile} --provision-only`,
      )
      break
    case 'missing-inputs':
    case 'profile-mismatch':
    case 'remote-execution':
      // both already printed an actionable message
      process.exitCode = 1
      break
    default:
      console.error(`\nProvisioning failed at: ${outcome.status}`)
      console.error(
        `The project is generated in ${projectSlug}/. Retry with:\n` +
          `  pnpm create-koras-app ${projectSlug} --profile ${ctx.profile} --provision-only`,
      )
      process.exitCode = 1
  }
}
