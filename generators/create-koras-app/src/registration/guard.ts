import type { ProfileManifest } from '../profiles/types.js'
import type { ProfileName } from '../profiles/loader.js'

/**
 * Whether this project registers itself with the Control Plane.
 *
 * The Control Plane never does. It is platform infrastructure, not an entry in
 * its own product registry, and registering it would make it a customer of
 * itself — invariant 2. The Control Plane rejects the attempt at its own edge
 * with a validator on `profile`, and the database carries the same constraint,
 * so this is the third of three independent refusals.
 *
 * Three is not excessive for this one. The generator is the only caller that
 * could plausibly make the mistake, since it is the only thing that provisions
 * a Control Plane at all, and a wrongly-registered Control Plane is not a
 * failed request but a platform that believes it is its own tenant.
 */
export type SkipReason = 'profile' | 'requested' | 'not-provisioned'

export interface RegistrationDecision {
  register: boolean
  reason?: SkipReason
  detail?: string
}

export function decideRegistration(options: {
  profile: ProfileName
  manifest: ProfileManifest
  skipRequested: boolean
  provisioned: boolean
}): RegistrationDecision {
  // Read from the manifest rather than compared against the string
  // 'control-plane'. The profile declares whether it registers; a future
  // profile that does not should not have to be added to a condition here.
  if (!options.manifest.registration.registers_as_product) {
    return {
      register: false,
      reason: 'profile',
      detail: `The ${options.profile} profile does not register as a product.`,
    }
  }

  // Ordered after the profile check on purpose. --skip-registration on a
  // control-plane run is not an override of anything; reporting it as one
  // would suggest the flag is what prevented the call.
  if (options.skipRequested) {
    return {
      register: false,
      reason: 'requested',
      detail:
        '--skip-registration was passed. The project exists and its infrastructure ' +
        'is provisioned; the Control Plane does not know about it yet.',
    }
  }

  // R-001: a product may be provisioned before any Control Plane is live, and
  // that is the documented bootstrap order rather than an error. Nothing to
  // register from either, since the payload is built from Terraform outputs.
  if (!options.provisioned) {
    return {
      register: false,
      reason: 'not-provisioned',
      detail: 'Nothing was provisioned, so there are no infrastructure references to register.',
    }
  }

  return { register: true }
}

/** The endpoint this profile registers against, as the manifest declares it. */
export function registrationEndpoint(manifest: ProfileManifest): string {
  return manifest.registration.endpoint ?? ''
}
