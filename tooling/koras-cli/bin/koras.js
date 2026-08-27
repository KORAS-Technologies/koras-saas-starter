#!/usr/bin/env node
// Thin shim that delegates to the compiled CLI in dist/.
//
// Deliberately plain JavaScript and deliberately not compiled: a check that
// dist/ is current cannot itself live in dist/.
import { readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')
const DIST = join(HERE, '..', 'dist')

/** Newest mtime under a directory, or 0 if it is not there. */
function newest(root) {
  let latest = 0
  let entries
  try {
    entries = readdirSync(root, { recursive: true, withFileTypes: true })
  } catch {
    return 0
  }
  for (const entry of entries) {
    if (!entry.isFile()) continue
    const time = statSync(join(entry.parentPath ?? entry.path, entry.name)).mtimeMs
    if (time > latest) latest = time
  }
  return latest
}

/**
 * Refuse to run a build that is older than the source it came from.
 *
 * The shim already refused when dist/ was missing, which is the easy half. The
 * half that matters is a build that exists and is behind, because that runs --
 * quietly, with whatever behaviour it had when it was made.
 *
 * It happened on the command where it costs most. `koras teardown` was run
 * against a real estate the day after ZITADEL gained a deleter, and the CLI
 * still reported ZITADEL as unsupported and listed it among the things it would
 * skip. Nothing was wrong with the message; it was yesterday's message. Had the
 * run gone ahead, four ZITADEL projects would have survived a teardown that
 * called itself complete.
 *
 * Erring toward false positives on purpose: touching a source file without
 * changing it trips this, and the remedy is one build. The opposite mistake is
 * silent and destructive.
 */
const sourceTime = newest(SRC)
const builtTime = newest(DIST)

if (builtTime === 0) {
  console.error('koras-cli is not built.\n  Run: pnpm --filter koras-cli build')
  process.exit(1)
}

if (sourceTime > builtTime) {
  const behind = Math.round((sourceTime - builtTime) / 1000)
  console.error(
    [
      '',
      `koras-cli was built ${behind}s before its source was last changed.`,
      '',
      'Refusing to run a stale build. This command deletes infrastructure, and',
      'an old build deletes what it knew about when it was made -- silently, and',
      'reporting the rest as complete.',
      '',
      '  pnpm --filter koras-cli build',
      '',
    ].join('\n'),
  )
  process.exit(1)
}

const { run } = await import('../dist/cli/index.js')

run(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
