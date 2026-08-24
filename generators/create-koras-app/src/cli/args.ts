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
  refreshModules: boolean
  /** Template-owned paths to overwrite from the generator's rendering. */
  refresh: string[]
  checkDrift: boolean
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
    refreshModules: false,
    refresh: [],
    checkDrift: false,
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
