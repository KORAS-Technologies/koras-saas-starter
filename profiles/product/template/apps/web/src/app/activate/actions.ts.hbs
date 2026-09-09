'use server'

/**
 * The welcome link, spent on the server.
 *
 * The owner of a new organization sets their first password here, on this
 * product's own page, and never on ZITADEL's. The Control Plane sends the
 * welcome, its link carries a token, this page reads whom it is for and then
 * posts the password; the Control Plane spends the token and sets the password
 * in ZITADEL server-side. The password crosses exactly two TLS hops and is not
 * stored, logged or echoed on either.
 *
 * Everything talks to `KORAS_CONTROL_PLANE_URL` from the server, like the
 * signup actions beside this file, and for the same reason: the address and
 * the shape of that API are the platform's, not something a browser bundle
 * should carry.
 *
 * Unknown, expired and spent links are one outcome. The Control Plane answers
 * them identically on purpose, and a page that guessed between them would undo
 * that: telling somebody their link "has expired" tells whoever is holding a
 * guessed token that it was once real.
 */

import { translator } from '../../lib/locale'
import type { ActivateState, ActivationDetails } from './state'

function controlPlane(): string | null {
  const base = process.env.KORAS_CONTROL_PLANE_URL
  return base ? base.replace(/\/$/, '') : null
}

export type DetailsOutcome =
  | { status: 'ok'; details: ActivationDetails }
  | { status: 'invalid' }
  | { status: 'rate-limited' }

/** Whom the link is for. Reading does not spend it. */
export async function activationDetails(token: string): Promise<DetailsOutcome> {
  const base = controlPlane()
  if (!base) return { status: 'invalid' }
  try {
    const response = await fetch(`${base}/api/signup/v1/activations/${encodeURIComponent(token)}`, {
      cache: 'no-store',
    })
    if (response.ok) {
      const body = (await response.json()) as {
        email?: string
        organization_name?: string
        product_code?: string
      }
      return {
        status: 'ok',
        details: {
          email: body.email ?? '',
          organizationName: body.organization_name ?? '',
          productCode: body.product_code ?? '',
        },
      }
    }
    if (response.status === 429) return { status: 'rate-limited' }
    return { status: 'invalid' }
  } catch {
    return { status: 'invalid' }
  }
}

/**
 * Set the password. The form's action.
 *
 * The two fields are compared here rather than only in the browser, because
 * the browser's check is a convenience and this is the one that counts. The
 * length floor matches the Control Plane's; ZITADEL's own policy for the
 * organization is applied when the password is set, and its refusal comes
 * back as a message under the field.
 */
export async function setPassword(_prev: ActivateState, form: FormData): Promise<ActivateState> {
  const t = await translator()
  const token = String(form.get('token') ?? '')
  const password = String(form.get('password') ?? '')
  const confirm = String(form.get('confirm') ?? '')

  if (!token) return { status: 'error', message: t('activate.invalid.description') }
  if (password.length < 8) {
    return { status: 'error', field: 'password', message: t('activate.form.tooShort') }
  }
  if (password !== confirm) {
    return { status: 'error', field: 'confirm', message: t('activate.form.mismatch') }
  }

  const base = controlPlane()
  if (!base) return { status: 'error', message: t('activate.failed') }

  try {
    const response = await fetch(`${base}/api/signup/v1/activations/${encodeURIComponent(token)}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password }),
      cache: 'no-store',
    })
    if (response.ok) return { status: 'ok' }
    if (response.status === 422) {
      // ZITADEL's password policy, in its own words. The one refusal the
      // person can act on, so it sits under the field.
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown }
      const detail = typeof body.detail === 'string' ? body.detail : t('activate.form.tooShort')
      return { status: 'error', field: 'password', message: detail }
    }
    if (response.status === 404) return { status: 'invalid' }
    if (response.status === 429) return { status: 'error', message: t('activate.rateLimited.description') }
    return { status: 'error', message: t('activate.failed') }
  } catch {
    return { status: 'error', message: t('activate.failed') }
  }
}
