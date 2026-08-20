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
  /** True when --output-dir was passed, as opposed to defaulting to cwd. */
  outputDirExplicit: boolean
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
    outputDirExplicit: false,
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
