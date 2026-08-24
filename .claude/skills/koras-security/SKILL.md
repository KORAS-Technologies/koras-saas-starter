---
name: koras-security
description: Koras Security Review guidance for Koras applications.
---

# Koras Security Review

Use this skill before completing changes that affect authentication, data access, APIs, uploads, payments, redirects, webhooks, integrations, or other trust boundaries.

## Review Checklist

### Identity and Access
- authentication enforced server-side
- authorization enforced per operation
- tenant isolation preserved
- least privilege for service credentials

### Input and Output
- validate untrusted input
- escape/render output safely
- avoid unsafe HTML injection
- validate URLs, redirect destinations, filenames, paths, IDs, and enum-like values

### Server-Side Requests
- defend against SSRF when destinations can be influenced by users
- restrict protocols/hosts as needed
- use timeouts

### Database
- use parameterized/query-builder operations
- prevent injection
- scope tenant-owned reads/writes

### File Uploads
- enforce size/type limits
- do not trust extension alone
- normalize filenames/paths
- prevent traversal/overwrite
- store outside executable/public paths unless intentional
- use malware/content scanning when risk warrants

### Secrets
Search for and reject:

```text
privileged secrets in NEXT_PUBLIC_ variables
hardcoded tokens
service-role keys in client code
console logging of tokens/session secrets
committed .env files
```

### Webhooks
- verify provider signature
- protect against replay when supported
- make processing idempotent
- do not trust payload ownership without verification

### Browser Security
Review applicable CSRF, CORS, CSP, iframe, cookie, and redirect behavior.

### Abuse Controls
Consider rate limiting, brute-force protection, expensive AI/API usage, email/SMS abuse, and resource exhaustion.

## Severity

Classify findings:

- CRITICAL: exploitable compromise/data exposure or unsafe privileged operation
- HIGH: serious security boundary failure
- MEDIUM: meaningful defense gap
- LOW: hardening or maintainability issue

Do not mark a feature complete with unresolved CRITICAL or HIGH findings.
