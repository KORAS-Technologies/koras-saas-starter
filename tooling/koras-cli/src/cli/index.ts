import { doctor } from '../doctor/run.js'
import { teardown, credentialsFromEnv } from '../teardown/run.js'
import { inventoryFromOutputs, qualify } from '../teardown/inventory.js'
import { parseTerraformOutputs } from 'create-koras-app/terraform-outputs'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
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

  teardown <product> --product-path <dir>
                             Remove the infrastructure of an acceptance run.
                             <dir> is the generated product, not its Terraform
                             directory. Pulls its own credentials from Doppler
                             and runs terraform output -json itself, so no
                             wrapper is typed, stdin stays free for the
                             confirmation prompt, and no credential is written
                             to disk.

                             Lists what it would delete and deletes nothing
                             unless KORAS_E2E_TEARDOWN=1 is set. Only resources
                             named koras-e2e-... can ever be deleted; a real
                             estate is refused by name.

  teardown <product> <src>   The same, reading outputs from a file, or from
                             stdin with a single dash. Cannot delete: the JSON
                             consumes stdin, so the confirmation prompt has
                             nothing to read the answer from.

EXAMPLES:
  pnpm koras bootstrap:doctor
  pnpm koras teardown koras-e2e-shop --product-path ../output/koras-e2e-shop

Both fetch what they need from Doppler (${BOOTSTRAP_DOPPLER_PROJECT} /
${BOOTSTRAP_DOPPLER_CONFIG}) by re-running themselves under it. Do not type a
wrapper; an outer one is detected rather than nested.

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
    // Same contract as bootstrap:doctor, and the same reason. The repository
    // rule is that credentials are pulled from Doppler by the CLI itself and no
    // wrapper is typed; teardown was the one command still asking for one, so
    // the documented command carried a `doppler run ... --` prefix that every
    // other command had stopped needing.
    //
    // `stdio: 'inherit'` matters more here than for the doctor: the child has
    // to inherit a real terminal or the confirmation prompt cannot be answered.
    if (
      shouldReexecUnderDoppler({
        required: true,
        satisfied: hasTeardownCredentials(),
      })
    ) {
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
 * Are the provider credentials already in the environment?
 *
 * Deliberately not "are they all there". A partial set is a real situation --
 * an operator with GITHUB_TOKEN exported and nothing else -- and the honest
 * answer is to fetch the rest rather than to proceed and report five providers
 * as skipped. One missing credential means one provider silently survives, so
 * the bar for skipping the fetch is that nothing is missing.
 */
function hasTeardownCredentials(): boolean {
  const c = credentialsFromEnv()
  return Boolean(
    c.githubToken &&
      c.dopplerToken &&
      c.supabaseToken &&
      c.upstashEmail &&
      c.upstashApiKey &&
      c.vercelToken &&
      c.flyToken,
  )
}

/**
 * `koras teardown <product> --product-path <dir>`
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
  const productSlug = args[0]
  const source = args[1]

  if (!productSlug) {
    console.error('usage: pnpm koras teardown <product-slug> --product-path <product-dir>')
    return 2
  }

  if (!source) {
    console.error(
      [
        '',
        'No Terraform outputs given. Let teardown read them:',
        '',
        `  pnpm koras teardown ${productSlug} --product-path ../output/${productSlug}`,
        '',
        'A file also works, and is worse. terraform output -json includes the',
        'values of outputs marked sensitive, so the file it writes holds live',
        'credentials -- Upstash URLs with their password, ZITADEL client secrets.',
        'One was committed to a public repository on 2026-08-26. Reading them',
        'here keeps them in memory and off the disk entirely.',
        '',
        'Piping with a dash keeps them off disk too, and cannot delete: the JSON',
        'consumes stdin, leaving the confirmation prompt nothing to read.',
        '',
      ].join(String.fromCharCode(10)),
    )
    return 2
  }

  let raw: string
  if (source === '--product-path') {
    const productPath = args[2]
    if (!productPath) {
      console.error('usage: pnpm koras teardown <product-slug> --product-path <product-dir>')
      return 2
    }
    // The product root, not its Terraform directory. The operator knows where
    // they generated it; `infrastructure/terraform` is this tool's own layout,
    // and asking them to append it is asking them to know an internal detail in
    // order to delete something.
    const dir = join(productPath, 'infrastructure', 'terraform')
    // Run Terraform rather than being piped its output.
    //
    // The pipe was the documented form and it cannot work: the JSON arrives on
    // stdin, is read to EOF, and then the confirmation prompt has nothing left
    // to read the answer from. It printed the prompt, took the empty string,
    // and cancelled -- which is the safe direction, and still meant the command
    // could not be completed the way its own runbook described.
    //
    // Reading it here keeps what the pipe was for. `terraform output -json`
    // includes the values of outputs marked sensitive, so the point was never
    // the pipe itself but that the credentials never reach disk. They still do
    // not: this is captured in memory and stdin stays free to answer with.
    const result = spawnSync('terraform', [`-chdir=${dir}`, 'output', '-json'], {
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    })
    if (result.error) {
      console.error(`Could not run terraform: ${result.error.message}`)
      return 1
    }
    if (result.status !== 0) {
      console.error(result.stderr?.trim() || `terraform exited ${String(result.status)}`)
      return 1
    }
    raw = result.stdout
  } else {
    try {
      // `-` reads stdin. Kept for scripts that already produce the JSON, and
      // no longer the documented form: see above.
      raw = source === '-' ? readFileSync(0, 'utf8') : readFileSync(source, 'utf8')
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err)
      console.error(`Could not read ${source}: ${detail}`)
      return 1
    }
  }

  let inventory
  try {
    inventory = qualify(inventoryFromOutputs(parseTerraformOutputs(raw)), productSlug)
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    console.error(`Could not parse the Terraform outputs: ${detail}`)
    return 1
  }

  // Deleting needs an answer typed at the prompt, and `-` has already spent
  // stdin reading the JSON. Refusing here beats printing a prompt that cannot
  // be answered -- which is what happened, and read as the command hanging or
  // ignoring the operator.
  if (source === '-' && process.env.KORAS_E2E_TEARDOWN === '1') {
    console.error(
      [
        '',
        'Cannot confirm a deletion when the outputs came from stdin: the JSON',
        'consumed it, so there is nothing left to read your answer from.',
        '',
        'Let teardown run Terraform instead, which leaves stdin free:',
        '',
        `  pnpm koras teardown ${productSlug} --product-path ../output/${productSlug}`,
        '',
      ].join(String.fromCharCode(10)),
    )
    return 2
  }

  const outcome = await teardown({
    inventory,
    // The command says "product" because that is what an operator generated
    // and what they type. The guards below judge a name and do not care which
    // profile produced it, so they keep the neutral term.
    projectSlug: productSlug,
    credentials: credentialsFromEnv(),
    fetchImpl: globalThis.fetch as never,
  })

  console.log(outcome.output)
  return outcome.failed ? 1 : 0
}
