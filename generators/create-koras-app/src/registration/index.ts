import type { GenerationContext } from '../generation/context.js'
import type { ProvisionOutputs } from '../terraform/outputs.js'
import { buildRegistration } from './contract.js'
import { decideRegistration, registrationEndpoint, type SkipReason } from './guard.js'
import { resolveRegistrationConfig } from './config.js'
import { resolveBearer } from './token.js'
import { registerProduct, type RegisterOptions } from './client.js'
import { compareRegistration } from './verify.js'

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
  /**
   * The Control Plane knows about this product. `confirmed` means it also
   * reported what it stored and every reference sent is stored as sent;
   * `unconfirmed` means it accepted the payload and did not say what it
   * holds, which is a Control Plane older than 2026-09-15. `detail` says
   * which, in words an operator can read.
   */
  | {
      kind: 'registered'
      correlationId: string
      confirmation: 'confirmed' | 'unconfirmed'
      detail: string
    }
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

  // The credential becomes a bearer here rather than in `config.ts`, because
  // minting is a network call and configuration resolution is not. A key that
  // cannot be exchanged fails the same way an unreachable Control Plane does —
  // it is reported, and it never unwinds the estate that has just been built.
  const bearer = await resolveBearer(resolution.config, options)
  if (!bearer.ok) {
    return { kind: 'failed', retryable: bearer.retryable, detail: bearer.detail }
  }

  const payload = buildRegistration(ctx, outputs)
  const outcome = await registerProduct(bearer.config, payload, options)

  switch (outcome.status) {
    case 'registered': {
      // Accepted is not stored. Until the Control Plane echoed its registry a
      // payload stored wrongly and one stored correctly were indistinguishable
      // here (F7), so the echo is compared rather than trusted, and a
      // difference fails the step: the estate is intact, and the registry
      // describing it is not, which is exactly what this step exists to say.
      if (outcome.stored === undefined) {
        return {
          kind: 'registered',
          correlationId: outcome.correlationId,
          confirmation: 'unconfirmed',
          detail:
            'Accepted, not confirmed: this Control Plane did not report what it ' +
            'stored, so the registry has not been checked against what was sent.',
        }
      }
      const verification = compareRegistration(payload, outcome.stored)
      if (!verification.confirmed) {
        return {
          kind: 'failed',
          retryable: false,
          correlationId: outcome.correlationId,
          detail:
            'The Control Plane accepted the registration but what it stored ' +
            'differs from what was sent: ' +
            verification.differences.join(', ') +
            '. The registry cannot be relied on for this product until the cause is found.',
        }
      }
      return {
        kind: 'registered',
        correlationId: outcome.correlationId,
        confirmation: 'confirmed',
        detail: 'Registry confirmed: every reference sent is stored as sent.',
      }
    }
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
export {
  resolveRegistrationConfig,
  deriveInstance,
  BASE_URL_VAR,
  TOKEN_VAR,
  KEY_VAR,
  PROJECT_ID_VAR,
} from './config.js'
export { mintToken, parseServiceAccountKey, resolveBearer } from './token.js'
export { registerProduct } from './client.js'
export { compareRegistration, parseStoredEnvironments } from './verify.js'
