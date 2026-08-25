import type { GenerationContext } from '../generation/context.js'
import type { ProvisionOutputs } from '../terraform/outputs.js'
import { buildRegistration } from './contract.js'
import { decideRegistration, registrationEndpoint, type SkipReason } from './guard.js'
import { resolveRegistrationConfig } from './config.js'
import { registerProduct, type RegisterOptions } from './client.js'

/**
 * The whole registration step, as one call the CLI can make and print.
 *
 * Composed here rather than in `cli/index.ts` so the ordering — decide, then
 * configure, then send — is testable without a CLI, and so the call site after
 * a successful `terraform apply` stays short enough to read.
 */

/** Why registration did not happen, including the reasons the guard cannot see. */
export type Reason = SkipReason | 'not-configured'

export type RegistrationReport =
  /** Nothing was sent, and nothing is wrong. */
  | { kind: 'skipped'; reason: Reason; detail: string }
  /** The Control Plane knows about this product. */
  | { kind: 'registered'; correlationId: string }
  /**
   * Something was wrong. `retryable` separates "try again later" from "this
   * will fail again the same way until a human changes something", which is
   * the only distinction the operator can act on.
   */
  | { kind: 'failed'; detail: string; retryable: boolean; correlationId?: string }

export interface RunRegistrationOptions extends RegisterOptions {
  skipRequested: boolean
  provisioned: boolean
  /** --control-plane-url, when the estate default is not the target. */
  urlOverride?: string
}

export async function runRegistration(
  ctx: GenerationContext,
  outputs: ProvisionOutputs | undefined,
  options: RunRegistrationOptions,
): Promise<RegistrationReport> {
  const decision = decideRegistration({
    profile: ctx.profile,
    manifest: ctx.manifest,
    skipRequested: options.skipRequested,
    provisioned: options.provisioned,
  })

  if (!decision.register) {
    // The guard always names a reason alongside a refusal, but the type does
    // not say so. Falling back rather than asserting means a future reason
    // added without a `detail` degrades to a vaguer message instead of
    // printing `undefined` at an operator.
    return {
      kind: 'skipped',
      reason: decision.reason ?? 'not-configured',
      detail: decision.detail ?? 'Registration did not run.',
    }
  }

  // The guard said this profile registers, so the manifest must say where. An
  // empty endpoint is a malformed profile rather than an absent Control Plane,
  // and reporting it as the latter would send an operator to look at Doppler
  // for a problem that is in a manifest.
  const endpoint = registrationEndpoint(ctx.manifest)
  if (endpoint === '') {
    return {
      kind: 'failed',
      retryable: false,
      detail:
        `The ${ctx.profile} profile registers as a product but declares no ` +
        'registration endpoint. Fix `registration.endpoint` in its manifest.',
    }
  }

  const resolution = resolveRegistrationConfig({
    endpoint,
    urlOverride: options.urlOverride,
    env: options.env,
  })

  if (!resolution.ok) {
    // R-001: no Control Plane configured is the documented bootstrap order —
    // the first product in a new estate is provisioned before the registry it
    // would register with exists. The other two are misconfigurations, and a
    // misconfiguration reported as "nothing to do" is one nobody fixes.
    if (resolution.problem.kind === 'no-base-url') {
      return {
        kind: 'skipped',
        reason: 'not-configured',
        detail:
          'No Control Plane is configured, so this product has not been registered ' +
          'with one. This is the expected bootstrap order for the first project in ' +
          'an estate.',
      }
    }
    return { kind: 'failed', retryable: false, detail: resolution.problem.detail }
  }

  // Unreachable in practice — the guard returns `not-provisioned` without
  // outputs — but the payload builder requires them, and narrowing here is
  // cheaper than a non-null assertion that a later refactor could invalidate.
  if (!outputs) {
    return {
      kind: 'skipped',
      reason: 'not-provisioned',
      detail: 'Terraform produced no outputs, so there are no references to register.',
    }
  }

  const outcome = await registerProduct(resolution.config, buildRegistration(ctx, outputs), options)

  switch (outcome.status) {
    case 'registered':
      return { kind: 'registered', correlationId: outcome.correlationId }
    case 'rejected':
      return {
        kind: 'failed',
        retryable: false,
        correlationId: outcome.correlationId,
        detail: `The Control Plane refused the registration (HTTP ${outcome.httpStatus}): ${outcome.detail}`,
      }
    case 'unreachable':
      return {
        kind: 'failed',
        retryable: true,
        correlationId: outcome.correlationId,
        detail: outcome.detail,
      }
  }
}

export { buildRegistration } from './contract.js'
export { decideRegistration, registrationEndpoint } from './guard.js'
export { resolveRegistrationConfig, BASE_URL_VAR, TOKEN_VAR } from './config.js'
export { registerProduct } from './client.js'
