# OWASP API Security Top 10 — review checklist

A record of what a generated KORAS API actually does about each risk, where it
is enforced, and what verifies it. Written against the **OWASP API Security Top
10 (2023)** because the surface being reviewed is an API rather than a
server-rendered site; the applications are covered by the web headers and CSP
rows at the end.

**Open gaps are listed as gaps.** A checklist whose every row is a tick is a
checklist nobody used, and the value of this document is in the three rows that
say *no*.

Status meanings:

| | |
|---|---|
| **Enforced** | Implemented, and a test fails if it stops being true |
| **Implemented** | In the code, with no test pinning it |
| **Gap** | Not addressed; the row says what would address it |
| **N/A** | Does not apply to what this template generates |

---

## API1:2023 — Broken Object Level Authorization

**Status: Enforced.**

Two independent layers, which is deliberate — the second exists because the
first is application code and application code is what forgets.

1. `require_tenant` resolves the caller's tenant from verified token claims and
   never from a request parameter. A caller who supplies a tenant id gets their
   own tenant regardless.
2. Row-level security scopes every query in the database itself, keyed on
   `app.tenant_id`, which `set_rls_context` sets **transaction-locally** — a
   session-scoped setting would outlive the request on a pooled connection and
   be inherited by whoever got that connection next.

`enable row level security` exempts the table owner, and the API connects as
the owner, so **`force row level security` is what makes layer 2 real**. Every
table now sets it. Without it the policies are present, correct, and never
consulted.

*Verified by:* `rls-enforcement.test.ts` (10 assertions, both profiles),
`supabase/tests/010_rls_structure.sql`, `supabase/tests/020_tenant_isolation.sql`.

## API2:2023 — Broken Authentication

**Status: Enforced.**

Tokens are verified against the issuing instance's JWKS in both tiers. Each
tier pins the signature, the audience, the issuer, and the algorithm:

| Path | Signature | Audience | Issuer | Algorithm |
|---|---|---|---|---|
| Next.js — ZITADEL id_token | JWKS | yes | yes | `RS256` |
| Next.js — session cookie | shared secret | — | yes | `HS256` |
| FastAPI — bearer token | JWKS | yes | yes | `RS256` |

The issuer and algorithm checks on the two ZITADEL paths were **added in Phase
12**; before that both pinned only the audience. Not directly exploitable — the
keys come from that instance, so a foreign signature fails anyway — but "the
next check would have caught it" is the argument that removes every check one
at a time.

A rejected token is logged and answered `401` with no detail, so an expired
token and a forged one are indistinguishable to the caller and distinguishable
to whoever is on call.

*Assumption:* the ZITADEL issuer equals the configured instance base URL. This
is how ZITADEL issues tokens. If an instance is ever fronted by a domain whose
`iss` differs, verification fails closed and loudly rather than opening.

*Verified by:* `jwt-validation.test.ts` (36 assertions), and 44 behavioural
tests in each generated project's `packages/auth`.

## API3:2023 — Broken Object Property Level Authorization

**Status: Implemented.**

Request and response bodies are Pydantic models on the API and Zod schemas on
the web tier, so neither accepts an unmodelled field nor returns one by
accident. The registration payload additionally builds only from Terraform
outputs that were not marked sensitive, so a credential cannot be serialised
into it however the builder is written.

*Gap:* no test asserts that a response model excludes internal columns. Adding
one is cheap and is the obvious next step for this row.

## API4:2023 — Unrestricted Resource Consumption

**Status: Gap.**

There is **no rate limiting** in the generated API. No per-caller quota, no
per-tenant quota, no request-size ceiling beyond the defaults of whatever sits
in front. An authenticated caller can issue unbounded requests, and an
unauthenticated one can hammer the token-verification path.

What would close it: a limiter keyed on tenant *and* subject rather than IP
(callers arrive through a CDN, so the IP is the CDN's), applied ahead of token
verification so the expensive path is the protected one, with the counter in
the environment's Upstash Redis rather than in process — the API runs more than
one machine, and an in-process counter is a per-machine counter.

*Tracked as:* this row. Nothing else records it today.

## API5:2023 — Broken Function Level Authorization

**Status: Implemented.**

Authentication and authorization are separate dependencies: `require_auth`
yields verified claims, `require_tenant` establishes trusted tenant context,
and role checks are made against claims rather than against anything the
browser sent. A verified caller lacking authority is `403`; an unverifiable one
is `401`.

The Control Plane's internal contract sits behind `platform_auth.py` on
`/internal/platform/v1`, separate from the public router and never exposed to a
browser.

*Gap:* no test asserts that every mutating route carries an authorization
dependency. A route added without one would not be caught.

## API6:2023 — Unrestricted Access to Sensitive Business Flows

**Status: N/A for the template.**

The generated API ships health and platform-contract routes only. This row
becomes live the moment a product adds sign-up, invitation, or billing flows,
and the mitigation is API4's limiter keyed to the flow rather than to the
caller.

## API7:2023 — Server Side Request Forgery

**Status: Implemented.**

The only outbound requests the template makes are to fixed, configured hosts:
the ZITADEL discovery document and JWKS, and the Control Plane registration
endpoint. No route takes a URL from a caller and fetches it.

Registration additionally refuses a base URL carrying credentials in userinfo,
and refuses plaintext to anything but a loopback address.

*Verified by:* `registration-client.test.ts`.

## API8:2023 — Security Misconfiguration

**Status: Enforced, with one note.**

- `docs_url` is disabled when `environment == 'prod'`; `redoc_url` always.
- CORS `allow_origins` defaults to `[]` — closed until configured explicitly.
- Security headers ship with every generated application, with the CSP left to
  middleware so it can carry a per-request nonce.
- Secrets come from Doppler only. Nothing is committed, and `.gitleaks.toml`
  ships to the starter and both templates with the scan running on `develop`.
- Terraform never auto-applies.

*Note:* once an origin is configured, CORS allows all methods and headers with
`allow_credentials=True`. That is a reasonable default for a first-party SPA
and worth narrowing for anything else.

*Verified by:* the security-headers suite, `state-artifacts.test.ts`,
`tests/security/test_no_state_artifacts.py`.

## API9:2023 — Improper Inventory Management

**Status: Implemented.**

Every generated repository carries `.koras/project.yaml` recording its
identity, profile, generator version, profile version, and enabled components —
and, once a Control Plane is live, registers those references with it, so the
estate has one inventory rather than none.

Environments are fixed at four per the environment strategy, with one Doppler
config and one Upstash database each; none is shared.

*Verified by:* the project-manifest suite, `registration-client.test.ts`,
`tests/e2e/product-provision.test.ts`.

## API10:2023 — Unsafe Consumption of APIs

**Status: Implemented.**

The provider's JWKS is the only third-party input that influences an
authorization decision, and it is consumed as a key set rather than as claims.
Control Plane responses are read for a status and a redacted summary and are
never trusted to carry authority.

Every response body and transport error passes through the redactor before it
is printed, because a 401 that quotes a bearer token back is how a token
reaches a log.

*Verified by:* `registration-client.test.ts`, `redact.test.ts`.

---

## Open gaps, collected

| Row | Gap | Severity |
|---|---|---|
| API4 | No rate limiting anywhere in the generated API | **High** |
| API3 | No test that response models exclude internal columns | Low |
| API5 | No test that every mutating route carries an authorization dependency | Low |

## What this checklist does not cover

The exit criterion for Phase 12 is "zero critical/high findings in automated
scans on `develop`". This document is a manual review and does not substitute
for that. The Security workflow — CodeQL, secret scanning, `gitleaks` — is
registered and has **never executed**, so the automated half of this phase is
unmeasurable rather than passing. See the Phase 11 note in
`IMPLEMENTATION_ROADMAP.md`.
