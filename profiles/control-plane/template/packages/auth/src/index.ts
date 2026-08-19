import type { NextRequest } from 'next/server'

/**
 * Claims carried by a Control Plane session.
 *
 * Unlike the product profile there is no `tenantId`: Control Plane staff act
 * across the estate rather than inside one tenant, so authorisation is by role
 * alone (`platform:admin` and friends).
 */
export interface JWTClaims {
  sub: string
  email: string
  name?: string
  roles: string[]
}

export interface Session {
  userId: string
  email: string
  claims: JWTClaims
}

export async function verifySession(request: NextRequest): Promise<Session | null> {
  const token = request.cookies.get('session')?.value
  if (!token) return null
  // Verification delegated to koras-auth server-side utility
  return null
}

export function getZitadelAuthUrl(callbackUrl: string): string {
  const params = new URLSearchParams({
    client_id: process.env.ZITADEL_CLIENT_ID ?? '',
    redirect_uri: process.env.ZITADEL_REDIRECT_URI ?? '',
    response_type: 'code',
    scope: 'openid email profile',
    state: callbackUrl,
  })
  return `${process.env.ZITADEL_DOMAIN}/oauth/v2/authorize?${params}`
}
