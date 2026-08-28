import { doctor } from '../doctor/run.js'
import { teardown, credentialsFromEnv } from '../teardown/run.js'
import { probeResources, type ProbeResult } from '../teardown/providers/index.js'
import { probe } from '../teardown/http.js'
import { plan } from '../teardown/guards.js'
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

  teardown <product> --product-path <dir> --verify
                             Ask every provider whether each resource is still
                             there. Read-only, and deletes nothing. Run it after
                             a teardown: a 404 counts as success, so the delete's
                             own output cannot tell "deleted" from "was never
                             found". Exits 1 if anything is alive or unknown.

                             Deletes the HCP Terraform workspace too, reading
                             its organization from the project's backend.tf --
                             so run this before removing the directory.

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
    // `process.exitCode`, not `process.exit()`.
    //
    // Calling process.exit() straight after an undici fetch aborts on Windows:
    //
    //   Assertion failed: !(handle->flags & UV_HANDLE_CLOSING),
    //   file src/win/async.c, line 76        (exit code 3221226505)
    //
    // It happens after the output is printed and the result is correct, which
    // is the confusing part -- the command answered and then could not leave.
    // Reproduced in a dozen lines: fetch, read the body, process.exit. Removing
    // the exit removes the crash, and Node still exits promptly on its own once
    // the sockets settle.
    //
    // Setting the code and returning does the same job without asking libuv to
    // tear down handles it is already closing.
    process.exitCode = await runTeardown(args.slice(1))
    return
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

    // Refuse before running Terraform at all, if the workspace is already gone.
    //
    // `terraform output` against a `remote` backend **creates the workspace
    // when it is missing**. So every teardown command -- the dry run included
    // -- puts back the resource a completed teardown deleted last, and then
    // reports it alive. A warning was not enough: it printed, the workspace was
    // re-created anyway, and the run exited 1 for a resource it had just made.
    //
    // Checked over HTTP, which creates nothing. A 404 means there is no state
    // to read and therefore nothing to tear down or verify.
    const backendCheck = readBackend(productPath)
    if (backendCheck.terraformWorkspace && backendCheck.terraformOrganization) {
      const gone = await workspaceIsGone(backendCheck)
      if (gone) {
        console.log(
          [
            '',
            `The HCP workspace ${backendCheck.terraformOrganization}/${backendCheck.terraformWorkspace} does not exist.`,
            '',
            'Nothing to do. Reading the Terraform outputs would create it --',
            'that is what a `remote` backend does with a workspace it cannot',
            'find -- so this stops instead, and the estate stays torn down.',
            '',
            'The generated directory can be removed now; see',
            'PROVISIONING_RUNBOOK.md section 5, step 6.',
            '',
          ].join(String.fromCharCode(10)),
        )
        return 0
      }
    }

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
    const outputs = parseTerraformOutputs(raw)
    const backend = readBackend(args[2])

    // Two different situations, and the first version of this said the second
    // when it meant the first.
    //
    // Empty outputs across the board means the estate was never applied: the
    // workspace exists because `terraform init` made it, and nothing else does.
    // Warning about DNS records there is noise, and noise next to a real
    // warning is how the real one stops being read.
    //
    // Outputs that exist but carry no cloudflare_record_ids is the case that
    // matters: a product generated before that output existed has records this
    // inventory cannot see. Said out loud rather than left to a count that only
    // counts what it knows about -- which is how eight of them outlived an
    // estate reporting nothing retained.
    const applied =
      outputs.githubRepository !== '' ||
      Object.keys(outputs.supabaseProjectRefs).length > 0 ||
      outputs.flyApps.length > 0
    if (!applied) {
      console.warn(
        [
          '',
          'No Terraform outputs beyond the workspace.',
          '',
          'This product has not been applied, or its state has been emptied.',
          'There is nothing to tear down but the workspace itself.',
          '',
        ].join(String.fromCharCode(10)),
      )
    } else if (Object.keys(outputs.cloudflareRecordIds).length === 0) {
      console.warn(
        [
          '',
          'No cloudflare_record_ids in the Terraform outputs.',
          '',
          'Either this product has no DNS records, or it was generated before',
          'that output existed and its records are invisible here. Check the',
          'zone, and see PROVISIONING_RUNBOOK.md section 5, step 3.',
          '',
        ].join(String.fromCharCode(10)),
      )
    }

    inventory = qualify(
      inventoryFromOutputs({ ...outputs, ...backend }),
      productSlug,
    )
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    console.error(`Could not parse the Terraform outputs: ${detail}`)
    return 1
  }

  // Read-only, and the reason it exists is that the delete's own output is not
  // evidence: 404 counts as success, so "deleted" and "was never there" print
  // the same. This asks each provider directly, afterwards.
  if (args.includes('--verify')) {
    // Reading the outputs already ran `terraform output -json`, and against a
    // `remote` backend that **creates the workspace if it is missing**. So a
    // standalone verify after a completed teardown puts back the one resource
    // the teardown deleted last, and then truthfully reports it alive.
    //
    // Observed, not theorised: two workspaces before, three after, the new one
    // stamped "a few seconds ago". Checked once in a directory where the
    // workspace still existed, which proved nothing and was reported as proof.
    //
    // This is why a delete run verifies itself at the end (below) instead of
    // being followed by a second command: that path runs Terraform once, before
    // deleting anything, and probes over HTTP afterwards.
    console.warn(
      [
        '',
        'Reading the outputs ran `terraform output`, which re-creates the HCP',
        'workspace when it is missing. If the teardown had already removed it,',
        'it exists again now and is reported below as alive.',
        '',
        'A delete run verifies itself; this flag is for checking an estate that',
        'has not been torn down yet.',
        '',
      ].join(String.fromCharCode(10)),
    )

    const results = await probeResources(
      globalThis.fetch as never,
      credentialsFromEnv(),
      plan(inventory).deletable,
    )

    console.log(formatProbes(results))
    return results.some((r) => r.liveness !== 'gone') ? 1 : 0
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

  // Verification belongs here rather than in a second command. Terraform has
  // already run, once, before anything was deleted; everything below is HTTP.
  // A second invocation would re-run `terraform output` and re-create the
  // workspace it had just removed.
  if (process.env.KORAS_E2E_TEARDOWN === '1' && !outcome.failed) {
    const results = await probeResources(
      globalThis.fetch as never,
      credentialsFromEnv(),
      plan(inventory).deletable,
    )
    console.log(formatProbes(results))
    const unresolved = results.filter((r) => r.liveness !== 'gone')
    if (unresolved.length > 0) return 1
  }

  return outcome.failed ? 1 : 0
}

/**
 * The HCP organization and workspace, read from the project's own backend.tf.
 *
 * Not a Terraform output -- the generator renders it into the backend block,
 * and by the time teardown runs there is no other record of it. Without this
 * the workspace is the one thing left on a "delete this by hand" list, holding
 * the state of an estate that no longer exists.
 *
 * A project whose backend.tf cannot be read yields empty strings, and the
 * inventory drops empty names, so an unreadable file loses the workspace rather
 * than failing the teardown of everything else.
 */
function readBackend(productPath: string | undefined): {
  terraformOrganization: string
  terraformWorkspace: string
} {
  const empty = { terraformOrganization: '', terraformWorkspace: '' }
  if (!productPath) return empty
  try {
    const text = readFileSync(join(productPath, 'infrastructure', 'terraform', 'backend.tf'), 'utf8')
    const org = /organization\s*=\s*"([^"]+)"/.exec(text)
    const name = /name\s*=\s*"([^"]+)"/.exec(text)
    if (!org || !name) return empty
    return { terraformOrganization: org[1] as string, terraformWorkspace: name[1] as string }
  } catch {
    return empty
  }
}

/** One line per resource, and a total that does not round `unknown` into either column. */
function formatProbes(results: ProbeResult[]): string {
  const width = Math.max(...results.map((r) => r.resource.kind.length), 0)
  const lines = ['', `Verified ${String(results.length)} resource(s) — nothing was deleted here.`, '']
  for (const r of results) {
    const mark = r.liveness === 'gone' ? 'gone   ' : r.liveness === 'alive' ? 'ALIVE  ' : 'unknown'
    lines.push(`  ${mark}  ${r.resource.kind.padEnd(width)}  ${r.resource.name}  (${r.detail})`)
  }

  const alive = results.filter((r) => r.liveness === 'alive').length
  const unknown = results.filter((r) => r.liveness === 'unknown').length
  lines.push('')
  lines.push(
    `${String(results.length - alive - unknown)} gone, ${String(alive)} still there, ` +
      `${String(unknown)} unknown.`,
  )
  if (unknown > 0) {
    lines.push('')
    lines.push('`unknown` is not `gone`. The provider did not say the resource was')
    lines.push('absent -- it refused, failed, or was never asked because a credential')
    lines.push('is missing. Check those by hand.')
  }
  lines.push('')
  return lines.join(String.fromCharCode(10))
}

/**
 * Is the HCP workspace already gone?
 *
 * Asked over HTTP, deliberately, because the obvious way to find out -- running
 * a Terraform command -- is the thing that would create it.
 *
 * Answers false when it cannot tell: no token, a refusal, a network failure.
 * Not knowing is not the same as knowing it is absent, and the cost of guessing
 * wrong in that direction is only that Terraform runs as it always did.
 */
async function workspaceIsGone(backend: {
  terraformOrganization: string
  terraformWorkspace: string
}): Promise<boolean> {
  const token = credentialsFromEnv().terraformToken
  if (!token) return false

  try {
    const status = await probe(
      globalThis.fetch as never,
      `https://app.terraform.io/api/v2/organizations/${encodeURIComponent(backend.terraformOrganization)}/workspaces/${encodeURIComponent(backend.terraformWorkspace)}`,
      { authorization: `Bearer ${token}`, 'content-type': 'application/vnd.api+json' },
    )
    return status === 404
  } catch {
    return false
  }
}
