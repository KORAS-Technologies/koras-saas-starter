---
name: koras-auth
description: Koras Authentication and Authorization guidance for Koras applications.
---

# Koras Authentication and Authorization

Use this skill for login, session, protected routes, user management, roles, permissions, service authentication, or identity-provider integration.

## Core Principle

Authentication proves identity. Authorization determines permitted actions. Never treat them as the same check.

## Protected Operation Checklist

For every protected server operation verify applicable:

1. authenticated principal
2. active/valid session or service identity
3. tenant context
4. required permission/role/capability
5. resource ownership or authorized tenant relationship
6. operation-specific constraints

## Client Guards

Client-side route guards and hidden buttons are UX only. They are not authorization boundaries.

## Session Rules

- Keep session/token handling aligned with the existing auth package.
- Do not log access tokens, refresh tokens, secrets, or full session objects.
- Handle expiry and logout explicitly.
- Avoid storing sensitive tokens in insecure browser storage when the architecture provides safer alternatives.
- Rotate/revoke credentials according to provider capabilities.

## Identity Provider Integration

Keep provider-specific API/UI details behind project abstractions where appropriate. Verify redirect URIs and state/nonce/PKCE behavior according to the chosen flow.

## Service Accounts

Service credentials are server-only. Apply least privilege and scope them to the required environment/resource.

## Errors

Do not reveal whether a sensitive account/resource exists when doing so creates enumeration risk.
