import { join } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
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
import {
  refreshSharedAssets,
  formatRefreshResult,
  refreshRenderedPaths,
  formatRefreshPathResult,
} from '../generation/refresh.js'
import { checkDrift, formatDriftReport } from '../generation/drift.js'
import { PROJECT_MANIFEST_PATH, parseProjectManifest } from '../generation/project-manifest.js'
import { provision, readOutputs } from '../terraform/runner.js'
import { runRegistration, type RegistrationReport } from '../registration/index.js'
import { runBillingProvision, BILLING_CATALOGUE_PATH } from '../billing/index.js'
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
  --push                     Initialise git in an already-provisioned project and
                             push it to the repository Terraform created. What
                             --provision does automatically, for the two-step
                             flow where generation and provisioning were
                             separate. Changes no infrastructure.
  --register-only            Re-send an existing project's references to the
                             Control Plane. Reads Terraform outputs; never
                             plans and never applies, so it cannot change
                             infrastructure. Use this to refresh a stale
                             registry entry.
  --provision-billing        Create this product's prices at the payment provider
                             and write their references onto its plans in the
                             Control Plane. Reads .koras/billing-catalogue.yaml.
                             Run it after registration and after
                             doppler-bootstrap. Never deletes, never archives and
                             never re-prices; a second run changes nothing. A
                             live provider key is refused anywhere but prod.
                             Add --dry-run to print what it would create.
  --check-drift              Report where an existing project no longer matches
                             the generator. Read-only; exits 1 on differences.
  --verbose                  With --check-drift --all, list repo-only files
                             individually rather than rolled up by directory.
  --never-fail               With --check-drift, always exit 0. For scheduled
                             runs, where drift is a standing condition rather
                             than a regression.
  --all                      With --check-drift, also list every other
                             generator-owned file that differs. Informational.
                             the generator. Read-only; exits 1 on differences.
  --refresh <path>           Overwrite one template-owned file from the
                             generator's rendering. Repeatable. Use
                             --check-drift --all to see what is stale first.
  --refresh-modules          Re-copy the shared Terraform modules into an
                             existing project. Combine with --provision-only to
                             plan against the refreshed copy.
  --dry-run                  Preview generation without writing files
  --output-dir <path>        Output parent directory (default: current directory)
  --skip-registration        Provision without registering the result with the
                             Control Plane. The project and its infrastructure
                             are unaffected; the Control Plane simply does not
                             learn about them. Use when no Control Plane is live
                             yet, which is the documented bootstrap order.
  --control-plane-url <url>  Control Plane to register with, overriding the
                             estate default from Doppler. The matching token is
                             read from Doppler only, never from a flag.
  --domain <fqdn>            Domain this project is served under. Defaults to
                             <slug>.<apex> for a product and the apex itself for
                             the Control Plane, where the apex is the profile's
                             domain_apex. Pass this when a product has its own
                             brand domain.
  --no-interactive           Disable interactive prompts
  --list-profiles            List available profiles and exit
  --help                     Show this help message

EXAMPLES:
  Generate only — no infrastructure is touched:
    pnpm create-koras-app docoris --profile product --output-dir ../output
    pnpm create-koras-app docoris --profile product --output-dir ../output --dry-run
    pnpm create-koras-app docoris --profile product --output-dir ../output \\
      --with marketing,ai_gateway
    pnpm create-koras-app docoris --profile product --output-dir ../output \\
      --with ai,ai_gateway
    pnpm create-koras-app koras-control-plane --profile control-plane --output-dir ../output

  Provision — credentials are pulled from Doppler automatically:
    pnpm create-koras-app docoris --profile product --provision --output-dir ../output

  Retry a run that failed partway — skips generation, keeps existing state:
    pnpm create-koras-app docoris --profile product --provision-only --output-dir ../output

  See whether a project has drifted from the starter:
    pnpm create-koras-app docoris --profile product --check-drift --output-dir ../output

  Pick up a module fixed in the starter since the project was generated:
    pnpm create-koras-app docoris --profile product --refresh-modules --output-dir ../output
    pnpm create-koras-app docoris --profile product --refresh-modules --provision-only \
      --output-dir ../output

  An outer \`doppler run\` is still honoured, and DOPPLER_PROJECT / DOPPLER_CONFIG
  override the profile's location for a one-off run.

Check the estate before provisioning: pnpm koras bootstrap:doctor
See docs/PROVISIONING_RUNBOOK.md for prerequisites and failure recovery.
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
  const existingProject =
    args.provisionOnly ||
    args.registerOnly ||
    args.provisionBilling ||
    args.push ||
    args.refreshModules ||
    args.checkDrift ||
    args.refresh.length > 0
  if (outputCheck.refused && !existingProject) {
    fail(outputCheck.message!)
  }

  const projectRoot = join(args.outputDir, projectSlug)

  if (existingProject) {
    // Retrying after a failed apply is routine, so this path deliberately
    // requires the directory the normal path refuses to overwrite.
    if (!existsSync(projectRoot)) {
      const flag = args.provisionOnly
        ? '--provision-only'
        : args.registerOnly
          ? '--register-only'
          : args.provisionBilling
            ? '--provision-billing'
            : args.push
            ? '--push'
            : args.checkDrift
          ? '--check-drift'
          : args.refreshModules
            ? '--refresh-modules'
            : '--refresh'
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
      required:
        args.provision ||
        args.provisionOnly ||
        args.registerOnly ||
        args.provisionBilling ||
        args.push,
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

  // An existing project's own components win over today's defaults.
  //
  // `--check-drift` and `--refresh` act on a project already on disk, and that
  // project may have been generated with `--with` or `--without`. Re-deriving
  // the selections from the profile defaults renders a different project and
  // reports every difference as drift -- so a project built with
  // `--with scheduler` was told its scheduler was drift, by the command whose
  // entire job is to say what has drifted.
  //
  // `.koras/project.yaml` records what it was generated with precisely so this
  // is knowable without the operator remembering which flags they used a year
  // ago. Explicit flags still win, for the case where the answer is being
  // changed rather than read.
  if (args.checkDrift || args.refresh.length > 0) {
    applyRecordedComponents(selections, projectRoot, {
      overridden: [...args.with, ...args.without],
    })
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
    domain: args.domain,
  })

  // ── Provision an existing project ──────────────────────────────────────────

  // ── Drift check ────────────────────────────────────────────────────────────
  // Read-only, and before any refresh, so what it reports is the state the
  // operator actually has rather than one this run has just corrected.

  if (args.checkDrift) {
    const report = checkDrift(ctx, projectRoot, { all: args.all })
    console.log(formatDriftReport(report, projectSlug, { verbose: args.verbose }))
    if (!args.refreshModules && !args.provisionOnly) {
      process.exit(!args.neverFail && report.findings.length > 0 ? 1 : 0)
    }
  }

  // ── Refresh shared modules ─────────────────────────────────────────────────
  // Before provisioning, so the plan that follows reflects the refreshed code
  // rather than the copy the project was generated with.

  if (args.refreshModules) {
    console.log(formatRefreshResult(await refreshSharedAssets(ctx, projectRoot)))
  }

  // Template-owned paths, named explicitly. After the shared assets so that a
  // single invocation can do both, and a named path always wins.
  if (args.refresh.length > 0) {
    console.log(formatRefreshPathResult(await refreshRenderedPaths(ctx, projectRoot, args.refresh)))
  }

  if ((args.refreshModules || args.refresh.length > 0) && !args.provisionOnly) return

  if (args.push) {
    await runPush(ctx, projectRoot, projectSlug)
    return
  }

  if (args.provisionBilling) {
    await runProvisionBilling(ctx, projectRoot, projectSlug, args)
    return
  }

  if (args.registerOnly) {
    await runRegisterOnly(ctx, projectRoot, projectSlug, args)
    return
  }

  if (args.provisionOnly) {
    console.log(`
Provisioning the existing project in ${projectSlug}/ — nothing regenerated.`)
    await runProvision(ctx, projectRoot, projectSlug, false, args)
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
  const result = await writeFiles(writeCtx, files)

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

  await runProvision(ctx, projectRoot, projectSlug, true, args)
}

/**
 * Put an already-provisioned project into the repository Terraform made for it.
 *
 * `--provision` does this as its last step. `--provision-only` deliberately does
 * not, and that is right: it operates on a tree the operator owns, and writing
 * files and committing during what was asked to be an infrastructure operation
 * would be the opposite of what this CLI promises.
 *
 * But there was no third option, so generating and provisioning as two steps
 * left a full estate, a repository holding one auto-init commit, and no
 * supported way to connect them. The operator was told only that "nothing was
 * committed" -- the fact, without the remedy. The seven manual steps existed,
 * printed solely when the automatic push *failed*, so the path that never
 * attempted one showed nothing at all.
 *
 * The repository name comes from Terraform outputs rather than from
 * `.koras/project.yaml`, which does not record it, and rather than from a guess
 * at `<org>/<slug>`. Pushing a product's source into the wrong repository is not
 * a mistake a retry undoes.
 *
 * Changes no infrastructure: `readOutputs` runs `init` and `output -json` and
 * has no path to a plan or an apply. `initAndPushToDevelop` asks before it
 * pushes, refuses to touch a directory that is already a repository, and checks
 * for Terraform state artifacts before `git add` rather than after -- the commit
 * is pushed moments later, and a credential that reaches a remote is published
 * whether or not a later commit removes it.
 */
async function runPush(
  ctx: import('../generation/context.js').GenerationContext,
  projectRoot: string,
  projectSlug: string,
): Promise<void> {
  console.log(`
Pushing ${projectSlug} to its repository — reading Terraform outputs, changing no infrastructure.`)

  const outcome = await readOutputs(ctx, { dryRun: false, projectRoot })

  switch (outcome.status) {
    case 'no-terraform':
      fail(
        `No Terraform configuration in ${projectSlug}/.\n` +
          '  --push operates on a project whose repository Terraform has created.',
      )
      return
    case 'init-failed':
      fail('terraform init failed, so the repository name could not be read. Nothing was pushed.')
      return
    case 'output-failed':
    case 'empty-state':
      fail(
        `${projectSlug} has no Terraform state, so no repository has been created for it.\n` +
          '  Provision it first: --provision-only. Nothing was pushed.',
      )
      return
    case 'read':
      break
  }

  const repositoryFullName = outcome.outputs.githubRepository
  if (!repositoryFullName) {
    fail(
      'The Terraform outputs name no GitHub repository, so there is nowhere to push.\n' +
        '  Nothing was pushed.',
    )
    return
  }

  try {
    await initAndPushToDevelop({ projectRoot, repositoryFullName })
  } catch (err) {
    fail(
      `${err instanceof Error ? err.message : String(err)}\n` +
        '  The project on disk and its infrastructure are both unaffected.',
    )
  }
}

/**
 * Re-send an existing project's references, changing nothing.
 *
 * Separate from `runProvision` rather than a flag on it, because the two differ in
 * what they are allowed to do rather than in what they happen to do. This path
 * reaches `readOutputs`, which runs `init` and `output -json` and has no code
 * path to a plan or an apply. An operator running this against a live estate is
 * risking a failed HTTP request, and nothing else.
 *
 * This is what F2c needed. Every product registered before 2026-08-28 has a
 * null `platform_api_base_url` and no `cloudflare_zone_id`, because
 * generation-time registration never sent either. Both are sent now, but the
 * only way to re-send them was `--provision-only` — a full plan across eight
 * providers and an apply — which is not a thing anyone does to fill in two
 * columns. References are upserted and never pruned, so this fills the gaps and
 * disturbs nothing else.
 */
/**
 * `--provision-billing`: the commercial catalogue, created and synced.
 *
 * Reads no Terraform state and runs no plan. The product's identity comes from
 * its manifest, exactly as `--register-only`'s does, and the two things it
 * talks to are the payment provider and the Control Plane.
 *
 * Every outcome is printed per plan and per interval rather than summarised.
 * This writes to an account that holds real money, and "3 plans provisioned"
 * is not something an operator can check; a price id beside an amount is.
 */
async function runProvisionBilling(
  ctx: import('../generation/context.js').GenerationContext,
  projectRoot: string,
  projectSlug: string,
  args: import('./args.js').ParsedArgs,
): Promise<void> {
  console.log(
    `\nProvisioning the commercial catalogue for ${projectSlug} — no infrastructure is touched.`,
  )

  const report = await runBillingProvision({
    projectRoot,
    productCode: projectSlug,
    registersAsProduct: ctx.manifest.registration.registers_as_product,
    dryRun: args.dryRun,
    urlOverride: args.controlPlaneUrl,
  })

  switch (report.kind) {
    case 'skipped':
      // Not an error, and exits 0. A profile with no catalogue, a project
      // generated before this existed, and an estate with no Control Plane yet
      // are all legitimate states -- the last one is the documented bootstrap
      // order (R-001), and failing on it would make the order impossible.
      console.log(`\n  Skipped: ${report.detail}`)
      return

    case 'planned':
      console.log(`\n  Dry run — nothing was sent.\n`)
      // A blank separator line must stay blank. Indenting it would give it two
      // spaces of trailing whitespace, which is invisible in a terminal and
      // shows up as a diff the first time anybody captures this into a file.
      for (const line of report.lines) console.log(line === '' ? '' : `  ${line}`)
      return

    case 'failed':
      fail(
        `The commercial catalogue was not provisioned.\n  ${report.detail}\n` +
          (report.retryable
            ? '  This looks retryable. Nothing was left half-done that a second run would ' +
              'duplicate: a price is found by its lookup key, so re-running is free.'
            : '  This will fail the same way until something is changed.') +
          (report.correlationId !== undefined
            ? `\n  Correlation id: ${report.correlationId}`
            : ''),
      )
      return

    case 'provisioned': {
      console.log(
        `\n  ${report.environment} — ${report.noop ? 'already current; nothing was created or written' : 'catalogue provisioned'}`,
      )

      for (const plan of report.plans) {
        console.log(`\n  ${plan.code}${plan.unchanged ? '  (plan row already current)' : ''}`)
        for (const interval of ['month', 'year'] as const) {
          const outcome = plan[interval]
          if (outcome === undefined) continue
          switch (outcome.kind) {
            case 'reused':
              console.log(`    ${interval}: ${outcome.amount}  ${outcome.priceId}  (already there)`)
              break
            case 'created':
              console.log(`    ${interval}: ${outcome.amount}  ${outcome.priceId}  (created)`)
              break
            case 'superseded':
              // Spelled out rather than reported as an update. A provider price
              // is immutable in amount, so this left a second price behind, and
              // an operator looking at a dashboard should know why there are
              // two before they wonder which one is live.
              console.log(
                `    ${interval}: ${outcome.amount}  ${outcome.priceId}  (new price; ` +
                  `${outcome.previousPriceId} was ${outcome.previousAmount ?? 'unknown'} and is ` +
                  'left in place, active and referenced by nothing)',
              )
              break
          }
        }
      }

      if (report.extraUser !== undefined) {
        // Said on every run, in the same breath as the prices. A price that
        // exists and charges nobody is harmless; one that exists and is
        // assumed to charge somebody is not.
        console.log('\n  Additional internal user — created, and billed by nothing yet')
        for (const interval of ['month', 'year'] as const) {
          const outcome = report.extraUser[interval]
          if (outcome === undefined) continue
          console.log(
            `    ${interval}: ${outcome.amount}  ${outcome.priceId}` +
              `  (${outcome.kind === 'reused' ? 'already there' : outcome.kind})`,
          )
        }
      }

      if (report.custom.length > 0) {
        console.log(
          `\n  Negotiated tiers, on the catalogue with no price: ${report.custom.join(', ')}`,
        )
      }

      if (report.unpriced.length > 0) {
        console.log(
          `\n  Declared with no amount, so left entirely alone: ${report.unpriced.join(', ')}`,
        )
      }

      // Printed on every successful run, not only on a dry run. This is what
      // keeps a declared-but-inert field from becoming the failure this
      // repository has shipped twice -- a setting rendered on a page and
      // honoured by nothing. Inertness that is stated is not a promise;
      // inertness a reader has to infer from the absence of an effect is.
      if (report.inert.length > 0) {
        console.log('\n  Declared in the catalogue and acted on by nothing yet:')
        for (const entry of report.inert) console.log(`    - ${entry}`)
      }

      console.log(
        `\n  Correlation id: ${report.correlationId}\n` +
          `  What was sent is the intent in ${BILLING_CATALOGUE_PATH}. The provider's amount\n` +
          "  remains the only one a customer sees or pays; the platform's billing.catalogue\n" +
          '  check is what compares the two from here on.',
      )
      return
    }
  }
}

async function runRegisterOnly(
  ctx: import('../generation/context.js').GenerationContext,
  projectRoot: string,
  projectSlug: string,
  args: import('./args.js').ParsedArgs,
): Promise<void> {
  console.log(`
Re-registering ${projectSlug} — reading Terraform outputs, changing nothing.`)

  const outcome = await readOutputs(ctx, { dryRun: false, projectRoot })

  switch (outcome.status) {
    case 'no-terraform':
      fail(
        `No Terraform configuration in ${projectSlug}/.\n` +
          '  --register-only re-sends the references of a provisioned project.',
      )
      return
    case 'init-failed':
      fail(
        'terraform init failed, so the outputs could not be read.\n' +
          '  Nothing was registered, and no infrastructure was touched.',
      )
      return
    case 'output-failed':
      fail(
        'terraform output failed, so there are no references to send.\n' +
          '  If this project has never been applied, provision it first with --provision-only.',
      )
      return
    case 'empty-state':
      // What a workspace looks like after a teardown, and also before the first
      // apply. The payload built from it is *accepted* rather than refused --
      // identity comes from the manifest, not from state -- so the Control Plane
      // would answer 200 and this would report success for a product nothing
      // backs. Refusing is the same judgement the deploy script already makes
      // about an empty service list.
      fail(
        `The Terraform workspace for ${projectSlug} is empty, so there is no infrastructure\n` +
          '  to register. That is what state looks like after a teardown, and also before\n' +
          '  the first apply.\n' +
          '  Registering from it would tell the Control Plane this product is current when\n' +
          '  nothing backs it, so nothing was sent.\n' +
          '  To register a newly provisioned estate, run --provision-only first.',
      )
      return
    case 'read':
      break
  }

  // `provisioned: true` states what the guard needs to know — that these
  // references describe infrastructure that exists — which is exactly what
  // having read them out of applied state proves.
  const report = await runRegistration(ctx, outcome.outputs, {
    skipRequested: args.skipRegistration,
    provisioned: true,
    urlOverride: args.controlPlaneUrl,
  })
  printRegistrationReport(report, ctx, projectSlug)

  // The exit code is the outcome. Unlike registration after an apply — where a
  // failure must not overshadow an estate that was successfully built — there
  // is nothing else this command did, so reporting success would be reporting
  // nothing at all.
  if (report.kind === 'failed') process.exit(1)
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
  args: import('./args.js').ParsedArgs,
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
        // The remedy, not just the fact. This path never attempts a push, so
        // the manual steps -- which print only when an *attempted* push fails --
        // never appeared, and an operator was left with a provisioned estate,
        // a repository holding one auto-init commit, and nothing saying how to
        // connect them.
        if (!existsSync(join(projectRoot, '.git'))) {
          console.log('')
          console.log('  The repository holds only its initial commit; this project is not in it yet.')
          console.log('  To put it there:')
          console.log(
            `    pnpm create-koras-app ${projectSlug} --profile ${ctx.profile} --push` +
              ` --output-dir <dir>`,
          )
        }
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
      // Registration is last on purpose. It reports what exists, so it runs
      // once the repository has been pushed and there is nothing further that
      // could change the references being registered.
      const report = await runRegistration(ctx, outcome.outputs, {
        skipRequested: args.skipRegistration,
        provisioned: true,
        urlOverride: args.controlPlaneUrl,
      })
      printRegistrationReport(report, ctx, projectSlug)

      for (const line of provisionedNextSteps(projectSlug)) console.log(line)
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

/**
 * Reports what registration did, and what to do when it did not work.
 *
 * A skip is not a warning: the common one is the first product in an estate
 * that has no Control Plane yet, which is the documented bootstrap order
 * rather than a problem.
 *
 * A failure is a warning and never an error that unwinds anything. The
 * infrastructure above this line was created successfully, and R-001 is
 * explicit that a registry being unreachable is not a reason to tear it down.
 * The exit code still moves so CI notices, but the message says plainly that
 * nothing needs repairing.
 */
function printRegistrationReport(
  report: RegistrationReport,
  ctx: import('../generation/context.js').GenerationContext,
  projectSlug: string,
): void {
  switch (report.kind) {
    case 'registered':
      console.log('\n✓ Registered with the Control Plane.')
      console.log(`  ${report.detail}`)
      console.log(`  Correlation id: ${report.correlationId}`)
      break

    case 'skipped':
      console.log(`\nControl Plane registration skipped — ${report.detail}`)
      if (report.reason === 'requested' || report.reason === 'not-configured') {
        console.log('  Register it later with:')
        console.log(
          `    pnpm create-koras-app ${projectSlug} --profile ${ctx.profile} --provision-only`,
        )
      }
      break

    case 'failed':
      console.warn(`\n⚠ Control Plane registration failed — ${report.detail}`)
      if (report.correlationId) console.warn(`  Correlation id: ${report.correlationId}`)
      console.warn('  The infrastructure was provisioned and is intact; nothing was rolled back.')
      console.warn(
        report.retryable
          ? '  Retry once the Control Plane is reachable:'
          : '  Fix the cause, then retry:',
      )
      // --register-only, not --provision-only. Registration is the only thing
      // that failed, and re-sending it needs no plan and no apply. Suggesting a
      // full provisioning run to recover from a failed HTTP request is how an
      // operator ends up re-planning eight providers to fix a timeout.
      console.warn(
        `    pnpm create-koras-app ${projectSlug} --profile ${ctx.profile} --register-only` +
          ` --output-dir <dir>`,
      )
      process.exitCode = 1
      break
  }
}

/**
 * Applies the components a project records to the selections used to render it.
 *
 * A read-only command acts on what is already on disk, so what matters is the
 * component set that project was built with -- not the profile's defaults
 * today, and not what a later release made default. Reading them back is why
 * `.koras/project.yaml` records them at all.
 *
 * A component named on the command line is left alone. `--check-drift --without
 * worker` is a question about what the project would look like without the
 * worker, and answering it from the recorded set would ignore the question.
 *
 * A manifest predating the `components` field records nothing, and this leaves
 * the defaults in place -- the same behaviour as before, for the projects that
 * behaviour was correct for.
 */
export function applyRecordedComponents(
  selections: import('../profiles/types.js').ComponentSelections,
  projectRoot: string,
  options: { overridden: string[] },
): void {
  const manifestPath = join(projectRoot, PROJECT_MANIFEST_PATH)
  if (!existsSync(manifestPath)) return

  let recorded: { applications: string[]; services: string[]; capabilities: string[] }
  try {
    const manifest = parseProjectManifest(readFileSync(manifestPath, 'utf8'), manifestPath)
    if (!manifest.components) return
    recorded = manifest.components
  } catch {
    // A manifest that cannot be parsed is the drift report's business rather
    // than this function's. It says so itself, and more usefully.
    return
  }

  const overridden = new Set(options.overridden)
  const categories = [
    ['applications', recorded.applications],
    ['services', recorded.services],
    ['capabilities', recorded.capabilities],
  ] as const

  for (const [category, enabled] of categories) {
    const on = new Set(enabled)
    for (const key of Object.keys(selections[category])) {
      if (overridden.has(key)) continue
      selections[category][key] = on.has(key)
    }
  }
}

/**
 * What to do once an estate exists.
 *
 * Extracted so it can be asserted. It printed `cd <slug>` and `make bootstrap`
 * and nothing else, which is the local Docker stack -- right for a generated
 * project, wrong for a provisioned one. Terraform creates the Doppler project
 * and its four configs and writes no setting into them; it cannot, knowing
 * neither the Supabase password nor the ZITADEL service token. So following the
 * tool's own instructions left every config empty, with no error anywhere and
 * an empty Secrets tab as the only sign.
 *
 * Nothing tested it, which is why it could say the wrong thing for as long as
 * it did.
 */
export function provisionedNextSteps(projectSlug: string): string[] {
  return [
    '',
    'Next steps — the estate exists, and nothing can deploy to it yet.',
    'Doppler holds a project and four empty configs; these fill them.',
    '',
    `  cd ${projectSlug}`,
    '',
    '  # 1. The restricted database role, once per environment. Prints the URL',
    '  #    for DATABASE_URL; keep the one you passed as DATABASE_ADMIN_URL.',
    '  bash local/scripts/create-app-role.sh "<privileged database url>"',
    '',
    '  # 2. What Doppler will be asked for. Writes nothing.',
    '  bash local/scripts/doppler-bootstrap.sh --dry-run',
    '',
    '  # 3. dev, test and stg -- then prod, which the first deliberately skips.',
    '  make doppler-bootstrap',
    '  make doppler-bootstrap-prod',
    '',
    '  # 4. Every environment holds every setting. Names only, never values.',
    '  make doppler-check',
    '',
    'make bootstrap starts the local Docker stack and is unrelated to the four',
    'steps above. See PROVISIONING_RUNBOOK.md section 1 in the starter.',
  ]
}
