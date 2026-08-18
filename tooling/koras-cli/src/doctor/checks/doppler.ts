import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import {
  BOOTSTRAP_DOPPLER_CONFIG,
  BOOTSTRAP_DOPPLER_PROJECT,
  missingBootstrapKeys,
  value,
} from '../env.js'

/**
 * Doppler is the sole secret authority, so this check is the root of the run:
 * it confirms the bootstrap config is reachable AND that every key a bootstrap
 * needs is actually present in this process.
 *
 * Only key *names* are ever examined. No value is read, printed, or compared.
 */
export async function checkDoppler(ctx: DoctorContext): Promise<DoctorResult> {
  const token = value(ctx.env, 'DOPPLER_TOKEN')
  if (!token) {
    return {
      passed: false,
      error:
        'DOPPLER_TOKEN is not set.\n' +
        `Run under: doppler run --project ${BOOTSTRAP_DOPPLER_PROJECT} ` +
        `--config ${BOOTSTRAP_DOPPLER_CONFIG} -- pnpm koras bootstrap:doctor`,
    }
  }

  const url =
    'https://api.doppler.com/v3/configs/config' +
    `?project=${encodeURIComponent(BOOTSTRAP_DOPPLER_PROJECT)}` +
    `&config=${encodeURIComponent(BOOTSTRAP_DOPPLER_CONFIG)}`

  try {
    await requestJson(ctx.fetchImpl, url, {
      headers: { authorization: `Bearer ${token}`, accept: 'application/json' },
    })
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return {
        passed: false,
        error:
          `DOPPLER_TOKEN was rejected (HTTP ${err.status}).\n` +
          `Check that it grants access to ${BOOTSTRAP_DOPPLER_PROJECT}/${BOOTSTRAP_DOPPLER_CONFIG}.`,
      }
    }
    if (err instanceof HttpError && err.status === 404) {
      return {
        passed: false,
        error: `Doppler config ${BOOTSTRAP_DOPPLER_PROJECT}/${BOOTSTRAP_DOPPLER_CONFIG} was not found.`,
      }
    }
    throw err
  }

  const missing = missingBootstrapKeys(ctx.env)
  if (missing.length > 0) {
    return {
      passed: false,
      error:
        `${missing.length} required bootstrap secret(s) are not in this environment:\n` +
        missing.map((name) => `  ${name}`).join('\n'),
    }
  }

  return { passed: true }
}

export const dopplerCheck: DoctorCheck = { label: 'Doppler', run: checkDoppler }
