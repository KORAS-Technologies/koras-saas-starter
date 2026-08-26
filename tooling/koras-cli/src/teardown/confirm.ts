import { createInterface } from 'node:readline/promises'
import { stdin, stdout } from 'node:process'

import type { Resource } from './guards.js'

/**
 * The last thing between a decision and a deletion.
 *
 * `confirmApply` in the generator asks for `yes` before creating
 * infrastructure. This asks for more, because the mistakes differ: applying to
 * the wrong project leaves resources that can be deleted, and deleting the
 * wrong project leaves nothing at all.
 *
 * So the operator types the project name. `yes` is a reflex by the third time
 * anyone sees it; a name has to be read off the screen and matched, which is
 * the point -- the prompt shows the name of the project *the inventory says it
 * is about*, so someone who meant a different one is typing a word that
 * contradicts what they are looking at.
 *
 * There is deliberately no --yes or --force flag. Every guard in this command
 * exists because the failure it prevents is unrecoverable, and a flag that
 * skips confirmation is the one thing a script would reach for.
 */

export interface ConfirmOptions {
  /** Injected for tests; defaults to a readline prompt on the real TTY. */
  ask?: (question: string) => Promise<string>
  isTTY?: boolean
}

export async function confirmTeardown(
  projectSlug: string,
  deletable: Resource[],
  options: ConfirmOptions = {},
): Promise<boolean> {
  const isTTY = options.isTTY ?? stdout.isTTY === true

  const byKind = new Map<string, number>()
  for (const resource of deletable) {
    byKind.set(resource.kind, (byKind.get(resource.kind) ?? 0) + 1)
  }

  console.log('')
  console.log('─'.repeat(72))
  console.log('  TEARDOWN — this permanently deletes real infrastructure')
  console.log('─'.repeat(72))
  console.log(`  Project:  ${projectSlug}`)
  console.log(`  Deleting: ${deletable.length} resource(s)`)
  for (const [kind, count] of [...byKind].sort()) {
    console.log(`              ${String(count).padStart(3)}  ${kind}`)
  }
  console.log('')
  console.log('  This cannot be undone. Databases are deleted with their contents.')
  console.log('')

  // A non-interactive session cannot give informed consent, and reading EOF as
  // agreement is how an automated run deletes an estate nobody meant to touch.
  if (!options.ask && !isTTY) {
    console.log('  Refusing to delete: no interactive terminal to confirm from.')
    console.log('')
    return false
  }

  const ask = options.ask ?? defaultAsk
  const answer = (await ask(`  Type the project name to confirm (${projectSlug}): `)).trim()

  if (answer !== projectSlug) {
    console.log('')
    console.log(
      `  Nothing deleted (answer was ${answer === '' ? 'empty' : `"${answer}"`}, expected "${projectSlug}").`,
    )
    console.log('')
    return false
  }

  return true
}

async function defaultAsk(question: string): Promise<string> {
  const rl = createInterface({ input: stdin, output: stdout })
  try {
    return await rl.question(question)
  } finally {
    rl.close()
  }
}
