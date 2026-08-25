import { doctor } from '../doctor/run.js'
import { teardown, credentialsFromEnv } from '../teardown/run.js'
import { inventoryFromOutputs, qualify } from '../teardown/inventory.js'
import { parseTerraformOutputs } from 'create-koras-app/terraform-outputs'
import { readFileSync } from 'node:fs'
import { BOOTSTRAP_DOPPLER_CONFIG, BOOTSTRAP_DOPPLER_PROJECT } from '../doctor/env.js'
import { preflightInputs } from 'create-koras-app/terraform'
import {
  dopplerUnavailableMessage,
  reexecUnderDoppler,
  shouldReexecUnderDoppler,
} from 'create-koras-app/doppler'

const HELP_TEXT = `
koras — KORAS platform CLI

USAGE:
  pnpm koras <command>

COMMANDS:
  bootstrap:doctor           Check that every bootstrap integration is configured
                             and reachable. Read-only.

  teardown <project>         Remove the infrastructure of an acceptance run.
                             Lists what it would delete and deletes nothing
                             unless KORAS_E2E_TEARDOWN=1 is set. Only resources
                             named koras-e2e-... can ever be deleted; a real
                             estate is refused by name.

EXAMPLES:
  doppler run --project ${BOOTSTRAP_DOPPLER_PROJECT} --config ${BOOTSTRAP_DOPPLER_CONFIG} -- \\
    pnpm koras bootstrap:doctor

Exits 0 when every integration passes, 1 otherwise.
See docs/PROVISIONING_RUNBOOK.md for what each check requires of the estate.
`.trim()

export async function run(argv: string[] = process.argv): Promise<void> {
  const args = argv.slice(2)
  const command = args[0]

  if (!command || command === '--help' || command === '-h' || command === 'help') {
    console.log(HELP_TEXT)
    process.exit(command ? 0 : 1)
  }

  if (command === 'teardown') {
    process.exit(await runTeardown(args.slice(1)))
  }

  if (command !== 'bootstrap:doctor') {
    console.error(`\nERROR: Unknown command "${command}".\n`)
    console.error(HELP_TEXT)
    process.exit(1)
  }

  // Every check needs the bootstrap secrets, so re-run under `doppler run`
  // rather than making the operator remember the wrapper. Mirrors what
  // create-koras-app does for --provision.
  if (shouldReexecUnderDoppler({ required: true, satisfied: preflightInputs().ok })) {
    const location = {
      project: process.env.DOPPLER_PROJECT ?? BOOTSTRAP_DOPPLER_PROJECT,
      config: process.env.DOPPLER_CONFIG ?? BOOTSTRAP_DOPPLER_CONFIG,
    }
    try {
      process.exit(await reexecUnderDoppler(location, process.argv))
    } catch {
      console.error(dopplerUnavailableMessage(location))
      process.exit(1)
    }
  }

  const outcome = await doctor()
  console.log(outcome.output)
  process.exit(outcome.code)
}

/**
 * `koras teardown <project> [outputs.json]`
 *
 * Reads what Terraform recorded rather than asking each provider what exists.
 * State is the record of what this configuration created; a listing is a guess
 * filtered by a name pattern, which can both miss and over-match.
 *
 * Deletes nothing unless KORAS_E2E_TEARDOWN=1. That is checked inside `apply`
 * rather than here, so the guarantee does not depend on this function being the
 * only caller.
 */
async function runTeardown(args: string[]): Promise<number> {
  const projectSlug = args[0]
  const outputsPath = args[1]

  if (!projectSlug) {
    console.error('usage: pnpm koras teardown <project-slug> [terraform-outputs.json]')
    return 2
  }

  if (!outputsPath) {
    // Read from a file rather than run `terraform output` for you. This command
    // deletes things, and what it deletes should come from something a person
    // can look at first.
    console.error(
      [
        '',
        'No Terraform outputs given.',
        '',
        '  terraform -chdir=<project>/infrastructure/terraform output -json > outputs.json',
        `  pnpm koras teardown ${projectSlug} outputs.json`,
        '',
      ].join(String.fromCharCode(10)),
    )
    return 2
  }

  let inventory
  try {
    const outputs = parseTerraformOutputs(readFileSync(outputsPath, 'utf8'))
    inventory = qualify(inventoryFromOutputs(outputs), projectSlug)
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    console.error(`Could not read ${outputsPath}: ${detail}`)
    return 1
  }

  const outcome = await teardown({
    inventory,
    credentials: credentialsFromEnv(),
    fetchImpl: globalThis.fetch as never,
  })

  console.log(outcome.output)
  return outcome.failed ? 1 : 0
}
