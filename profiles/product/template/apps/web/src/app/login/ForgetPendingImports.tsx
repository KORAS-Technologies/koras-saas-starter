'use client'

import { useEffect } from 'react'
import { purgePending } from '../dashboard/imports/source-state'

/**
 * Whoever is on the sign-in page has no session, so no remembered import wait
 * is theirs to keep: it names a file and belongs to a principal who has left.
 * Signing out lands here, as does an expired session and a switch of account,
 * so one place clears it for all three. Renders nothing.
 */
export function ForgetPendingImports() {
  useEffect(() => {
    try {
      purgePending(null, window.localStorage)
    } catch {
      // Storage can be blocked; the wait was a convenience and is also scoped by key.
    }
  }, [])
  return null
}
