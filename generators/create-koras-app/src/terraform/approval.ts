import { createInterface } from 'node:readline/promises'
import { stdin, stdout } from 'node:process'

export interface ApprovalRequest {
  projectName: string
  projectSlug: string
  profile: string
  /** Resource counts parsed from the plan, if Terraform reported them. */
  planSummary?: string
}

export interface ApprovalOptions {
  /** Injected for tests; defaults to a readline prompt on the real TTY. */
  ask?: (question: string) => Promise<string>
  isTTY?: boolean
}

/**
 * Terraform is never applied without an explicit human decision.
 *
 * The operator must type `yes` in full — `y`, `Y`, and an empty line are all
 * refusals. There is deliberately no --auto-approve flag: a generator rule
 * forbids applying infrastructure without confirmation, so no code path may
 * bypass this function.
 */
export async function confirmApply(
  request: ApprovalRequest,
  options: ApprovalOptions = {},
): Promise<boolean> {
  const isTTY = options.isTTY ?? stdout.isTTY === true

  console.log('')
  console.log('─'.repeat(72))
  console.log('  TERRAFORM APPLY — this creates real infrastructure')
  console.log('─'.repeat(72))
  console.log(`  Project:  ${request.projectName} (${request.projectSlug})`)
  console.log(`  Profile:  ${request.profile}`)
  if (request.planSummary) console.log(`  Plan:     ${request.planSummary}`)
  console.log('')
  console.log('  Review the plan above. Resources are created across GitHub,')
  console.log('  Doppler, Supabase, ZITADEL, Vercel, Fly.io, and Cloudflare.')
  console.log('')

  // A non-interactive session cannot give informed consent, so it is a refusal
  // rather than a prompt that silently reads EOF as agreement.
  if (!options.ask && !isTTY) {
    console.log('  Refusing to apply: no interactive terminal to confirm from.')
    console.log('  Re-run with a TTY, or run `terraform apply` yourself after review.')
    console.log('')
    return false
  }

  const ask = options.ask ?? defaultAsk
  const answer = (await ask('  Apply infrastructure? Type "yes" to proceed: ')).trim()

  if (answer !== 'yes') {
    console.log('')
    console.log(`  Not applied (answer was ${answer === '' ? 'empty' : `"${answer}"`}).`)
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
