/**
 * Secret redaction, re-exported from the generator that owns it.
 *
 * The implementation moved to `create-koras-app` when the Control Plane
 * registration client needed the same guarantee: it holds a bearer token and
 * reads response bodies from a server that may quote one back. Two redactors
 * would be two chances to fix a leak in only one of them, so there is one, and
 * it lives in the package `koras-cli` already depends on rather than the other
 * way round.
 *
 * This module stays so the doctor's call sites read as they always did.
 */
export { redact, isSensitiveName } from 'create-koras-app/redact'
