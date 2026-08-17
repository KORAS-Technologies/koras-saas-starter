import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

export interface OutputDirCheck {
  refused: boolean
  message?: string
}

/**
 * True when the directory is the koras-saas-starter repository itself.
 *
 * Checked by package name plus the two directories only the starter has, so a
 * generated project — which also carries profiles/-shaped paths in its
 * templates — is never mistaken for it.
 */
export function isStarterRepository(dir: string): boolean {
  const packagePath = join(dir, 'package.json')
  if (!existsSync(packagePath)) return false

  try {
    const parsed = JSON.parse(readFileSync(packagePath, 'utf8')) as { name?: string }
    if (parsed.name !== 'koras-saas-starter') return false
  } catch {
    return false
  }

  return existsSync(join(dir, 'profiles')) && existsSync(join(dir, 'generators', 'create-koras-app'))
}

/**
 * Generating into the starter repository pollutes it with a full project tree
 * that no .gitignore covers. It is almost always an accident — the default
 * output directory is the current one, and the starter is where you happen to
 * be standing when you run the generator.
 *
 * Refused unless --output-dir says so explicitly.
 */
export function checkOutputDirectory(outputDir: string, explicit: boolean): OutputDirCheck {
  const resolved = resolve(outputDir)

  if (!isStarterRepository(resolved) || explicit) return { refused: false }

  return {
    refused: true,
    message: [
      `Refusing to generate inside the koras-saas-starter repository:`,
      `  ${resolved}`,
      '',
      '  A generated project is its own repository and does not belong here —',
      '  nothing in .gitignore covers it.',
      '',
      '  Choose a destination:',
      '    pnpm create-koras-app <project> --profile <profile> --output-dir ..',
      '',
      '  Or pass --output-dir . explicitly if you really mean this directory.',
    ].join('\n'),
  }
}
