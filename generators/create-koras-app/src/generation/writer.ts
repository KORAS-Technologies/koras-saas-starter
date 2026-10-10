import { mkdir, writeFile, rename } from 'node:fs/promises'
import { join, dirname } from 'node:path'
import { randomBytes } from 'node:crypto'
import type { RenderedFile } from './engine.js'
import type { GenerationContext } from './context.js'
import { PROJECT_MANIFEST_PATH } from './project-manifest.js'

export interface WriteResult {
  filesWritten: number
  fileList: string[]
}

/**
 * Files an interpreter reads by shebang, or a Linux container executes.
 *
 * These must be LF whatever the generating machine does. A template checked
 * out on Windows with `core.autocrlf=true` carries CRLF, and copying those
 * bytes verbatim produces a project whose `make bootstrap` dies on
 * `set -euo pipefail\r: invalid option name` — with the stray carriage return
 * scrambling the error message that would have explained it.
 *
 * The generated `.gitattributes` pins these too, but that only takes effect
 * once the project is committed and checked out again. This covers the first
 * run, before there is any git history at all.
 *
 * A file that starts with a hashbang is one too, whatever it is called. The
 * name list missed `local/scripts/stack.mjs`, and a CRLF hashbang is not
 * harmless there: Vite's SSR transform recognises a hashbang only when it ends
 * in LF, so under vitest a CRLF `stack.mjs` failed to load with "SyntaxError:
 * Invalid or unexpected token" (2026-10-10). Asking the content rather than
 * extending the list covers the next `.mjs`, `.py` or extensionless entrypoint
 * as well. The starter's own `.gitattributes` pins LF for every text file since
 * the same day, so this is for a checkout that does not honour it.
 */
export function requiresUnixLineEndings(outputPath: string, content?: Buffer | string): boolean {
  const name = outputPath.split('/').pop() ?? ''
  return (
    /\.(sh|bash|mk)$/.test(name) ||
    name === 'Makefile' ||
    name === 'Dockerfile' ||
    name.endsWith('.Dockerfile') ||
    (content !== undefined && startsWithHashbang(content))
  )
}

function startsWithHashbang(content: Buffer | string): boolean {
  return typeof content === 'string'
    ? content.startsWith('#!')
    : content.length >= 2 && content[0] === 0x23 && content[1] === 0x21
}

/** Collapses CRLF to LF. Leaves a lone CR alone — that is data, not a line ending. */
export function toUnixLineEndings(content: Buffer | string): Buffer | string {
  if (typeof content === 'string') return content.replace(/\r\n/g, '\n')
  return content.includes('\r\n') ? Buffer.from(content.toString('utf8').replace(/\r\n/g, '\n')) : content
}

/**
 * Asynchronous on purpose. A generated project is several hundred files, and
 * writing them synchronously holds the event loop for as long as the disk
 * takes -- over a minute on a slow one. A vitest worker that cannot answer
 * the reporter for that long is torn down and its tests reported failed
 * (R-031). Writes are still sequential and still atomic; only the waiting
 * changed.
 */
export async function writeFiles(
  ctx: GenerationContext,
  files: RenderedFile[],
): Promise<WriteResult> {
  const projectRoot = join(ctx.outputDir, ctx.projectSlug)
  const fileList: string[] = []

  for (const file of files) {
    const outputAbsPath = join(projectRoot, file.outputPath)
    fileList.push(file.outputPath)

    if (ctx.dryRun) continue

    // Atomic write: write to temp file then rename
    const dir = dirname(outputAbsPath)
    await mkdir(dir, { recursive: true })

    const content = requiresUnixLineEndings(file.outputPath, file.content)
      ? toUnixLineEndings(file.content)
      : file.content

    const tmpPath = `${outputAbsPath}.${randomBytes(4).toString('hex')}.tmp`
    if (typeof content === 'string') {
      await writeFile(tmpPath, content, 'utf8')
    } else {
      await writeFile(tmpPath, content)
    }
    await rename(tmpPath, outputAbsPath)
  }

  return { filesWritten: ctx.dryRun ? 0 : files.length, fileList }
}

function enabled(selected: Record<string, boolean>): string {
  const names = Object.entries(selected)
    .filter(([, on]) => on)
    .map(([name]) => name)
  return names.length > 0 ? names.join(', ') : '(none)'
}

export function printDryRunManifest(ctx: GenerationContext, files: RenderedFile[]): void {
  console.log('\nKORAS Generator — Dry Run')
  console.log(`Profile:  ${ctx.profile}`)
  console.log(`Project:  ${ctx.projectName}`)
  console.log(`Slug:     ${ctx.projectSlug}`)
  console.log(`Output:   ${join(ctx.outputDir, ctx.projectSlug)}`)
  console.log(`Apps:     ${enabled(ctx.selections.applications)}`)
  console.log(`Services: ${enabled(ctx.selections.services)}`)
  console.log(`Register: ${ctx.manifest.registration.registers_as_product ? 'yes' : 'no'}`)
  // Called out by name: it is the file KORAS tooling identifies the project by,
  // and one line in a list of ~180 is easy to miss.
  console.log(`Manifest: ${ctx.projectSlug}/${PROJECT_MANIFEST_PATH}\n`)
  console.log(`FILES TO CREATE (${files.length} files):`)
  // Sorted rather than shown in template-walk order: generator-authored files
  // are appended after the template tree, so walk order buries them at the
  // bottom, far from the neighbours a reader scans for. Sorting also makes the
  // listing stable regardless of how the directory walk happens to enumerate.
  for (const path of files.map((f) => f.outputPath).sort()) {
    console.log(`  ${ctx.projectSlug}/${path}`)
  }
  // With --provision the source IS written: Terraform can only plan a
  // configuration that exists on disk, so the dry run applies to the
  // infrastructure, not the files. Saying otherwise here would contradict the
  // "Generated N files" line printed moments later, and leave an operator
  // unsure whether a directory now exists on their machine.
  console.log(
    ctx.provision
      ? '\nThe project above IS written to disk — Terraform can only plan a' +
          '\nconfiguration that exists. No infrastructure is created.'
      : '\nNo files were written. Remove --dry-run to proceed.',
  )
}
