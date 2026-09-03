export interface ParsedArgs {
  project?: string
  profile?: string
  provision: boolean
  dryRun: boolean
  outputDir: string
  noInteractive: boolean
  help: boolean
  listProfiles: boolean
  /** Optional components to enable, e.g. --with marketing,ai_gateway */
  with: string[]
  /** Optional components to disable, e.g. --without worker */
  without: string[]
  /** Provision an already-generated project; skips generation entirely. */
  provisionOnly: boolean
  /**
   * Re-register an already-provisioned project, changing no infrastructure.
   *
   * Reads Terraform outputs and sends them. It never plans and never applies,
   * which is what makes it usable on a live estate: the heaviest thing it can
   * do is fail to reach the Control Plane.
   *
   * The client's own comment has always described this as "the operator's
   * `--register-only`" — it just did not exist, so the only way to re-send a
   * reference was a full `--provision-only`. That is why every product
   * registered before 2026-08-28 still has a null `platform_api_base_url`
   * (F2c): the fix was a re-provision, and nobody re-provisions an estate to
   * fill in two columns.
   */
  registerOnly: boolean
  /**
   * Initialise git and push an already-provisioned project to its repository.
   *
   * `--provision` does this itself, as the last step of generating and building
   * an estate in one go. `--provision-only` deliberately does not: it operates
   * on a tree the operator owns, and writing files and committing during what
   * was asked to be an infrastructure operation is the wrong thing.
   *
   * That left the two-step flow -- generate, then `--provision-only` -- with a
   * provisioned estate, a GitHub repository holding one auto-init commit, and no
   * supported way to put the code in it. Found by noticing, which is how it
   * would have kept being found.
   */
  push: boolean
  refreshModules: boolean
  /** Template-owned paths to overwrite from the generator's rendering. */
  refresh: string[]
  checkDrift: boolean
  verbose: boolean
  neverFail: boolean
  all: boolean
  /** True when --output-dir was passed, as opposed to defaulting to cwd. */
  outputDirExplicit: boolean
  /**
   * Provision without telling the Control Plane about the result.
   *
   * R-001's mitigation is written as though this exists: a product may be
   * provisioned before any Control Plane is live, and registration failing is
   * not a reason to unwind infrastructure that succeeded.
   */
  skipRegistration: boolean
  /**
   * The Control Plane to register with, when it is not the estate default.
   *
   * The default arrives from Doppler as KORAS_CONTROL_PLANE_URL. This overrides
   * it for a one-off run -- a disposable lab project pointed at a locally-run
   * Control Plane, most often. There is deliberately no matching flag for the
   * token: a base URL is not a secret and a bearer token is, and a token passed
   * on a command line is one in the shell history and the process table.
   */
  controlPlaneUrl?: string
  /**
   * The domain this project is served under, when it has its own.
   *
   * Absent, a product is namespaced beneath the profile's `domain_apex` as
   * `<slug>.<apex>` and the Control Plane takes the apex itself. See R-028.
   */
  domain?: string
}

function splitList(value: string | undefined): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

export function parseArgs(argv: string[]): ParsedArgs {
  const args = argv.slice(2)
  const result: ParsedArgs = {
    provision: false,
    dryRun: false,
    outputDir: process.cwd(),
    noInteractive: false,
    help: false,
    listProfiles: false,
    with: [],
    without: [],
    provisionOnly: false,
    registerOnly: false,
    push: false,
    refreshModules: false,
    refresh: [],
    checkDrift: false,
    verbose: false,
    neverFail: false,
    all: false,
    outputDirExplicit: false,
    skipRegistration: false,
  }

  let i = 0
  while (i < args.length) {
    const arg = args[i]
    switch (arg) {
      case '--help':
      case '-h':
        result.help = true
        break
      case '--list-profiles':
        result.listProfiles = true
        break
      case '--provision':
        result.provision = true
        break
      case '--provision-only':
        // Implies --provision: there is nothing else this flag could mean.
        result.provisionOnly = true
        result.provision = true
        break
      case '--push':
        // Like --register-only, this operates on an existing project and
        // changes no infrastructure. It reads Terraform outputs for the
        // repository name rather than guessing it: pushing a product's source
        // to the wrong repository is not a mistake a retry undoes.
        result.push = true
        break
      case '--register-only':
        // Deliberately does NOT imply --provision. It reads Terraform outputs
        // and sends them; it never plans and never applies. Turning a
        // re-registration into an infrastructure run would be the opposite of
        // what this flag is for, and it is the reason re-registration has been
        // avoided rather than done.
        result.registerOnly = true
        break
      case '--all':
        // Widens --check-drift to every generator-owned file. Informational
        // only: those files are edited by healthy projects, so they cannot
        // gate anything.
        result.all = true
        break
      case '--check-drift':
        // Read-only. Reports where a project no longer matches the
        // generator; never writes and never provisions.
        result.checkDrift = true
        break
      case '--verbose':
        // With --check-drift --all, lists the repo-only files individually
        // instead of rolling them up by directory. There are ~291 of them in
        // koras-control-plane, which is a report and not a summary.
        result.verbose = true
        break
      case '--never-fail':
        // Exit 0 whatever is found. For the scheduled run: drift is a standing
        // condition of a healthy project, not a regression introduced by the
        // commit that happened to trigger the job, and a nightly job that goes
        // red and stays red is one people mute rather than read.
        result.neverFail = true
        break
      case '--refresh':
        // Overwrites specific template-owned files from the generator's
        // rendering. Separate from --refresh-modules because the two differ in
        // who owns the file: shared assets are the starter's and can be
        // recopied wholesale, while a rendered file may carry edits the project
        // meant to keep. Naming the path is the consent, so nothing is
        // discovered and overwritten in the same breath -- use --check-drift
        // --all to find out what is stale first.
        result.refresh.push(args[++i])
        break
      case '--refresh-modules':
        // Re-copies the shared Terraform modules into a project already on
        // disk. Deliberately does NOT imply --provision: refreshing is a
        // read-then-write of source files, and quietly turning that into an
        // infrastructure run would be the opposite of what this CLI promises.
        result.refreshModules = true
        break
      case '--dry-run':
        result.dryRun = true
        break
      case '--no-interactive':
        result.noInteractive = true
        break
      case '--profile':
        result.profile = args[++i]
        break
      case '--output-dir':
        result.outputDir = args[++i]
        result.outputDirExplicit = true
        break
      case '--domain':
        result.domain = args[++i]
        break
      case '--skip-registration':
        result.skipRegistration = true
        break
      case '--control-plane-url':
        result.controlPlaneUrl = args[++i]
        break
      case '--with':
        result.with.push(...splitList(args[++i]))
        break
      case '--without':
        result.without.push(...splitList(args[++i]))
        break
      default:
        if (arg.startsWith('--profile=')) {
          result.profile = arg.split('=')[1]
        } else if (arg.startsWith('--output-dir=')) {
          result.outputDir = arg.split('=')[1]
          result.outputDirExplicit = true
        } else if (arg.startsWith('--control-plane-url=')) {
          result.controlPlaneUrl = arg.slice('--control-plane-url='.length)
        } else if (arg.startsWith('--domain=')) {
          result.domain = arg.slice('--domain='.length)
        } else if (arg.startsWith('--with=')) {
          result.with.push(...splitList(arg.slice('--with='.length)))
        } else if (arg.startsWith('--without=')) {
          result.without.push(...splitList(arg.slice('--without='.length)))
        } else if (!arg.startsWith('-')) {
          result.project = arg
        }
    }
    i++
  }

  return result
}
