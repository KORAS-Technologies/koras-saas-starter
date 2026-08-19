import { doctor } from '../doctor/run.js'
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

EXAMPLES:
  doppler run --project ${BOOTSTRAP_DOPPLER_PROJECT} --config ${BOOTSTRAP_DOPPLER_CONFIG} -- \\
    pnpm koras bootstrap:doctor

Exits 0 when every integration passes, 1 otherwise.
See PROVISIONING_RUNBOOK.md for what each check requires of the estate.
`.trim()

export async function run(argv: string[] = process.argv): Promise<void> {
  const args = argv.slice(2)
  const command = args[0]

  if (!command || command === '--help' || command === '-h' || command === 'help') {
    console.log(HELP_TEXT)
    process.exit(command ? 0 : 1)
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
