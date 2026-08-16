# KORAS SaaS Starter — Risk Register

## Overview

This register tracks identified risks to the delivery and operation of the
`koras-saas-starter` and its generated projects. Each entry includes a
likelihood rating, impact rating, overall severity, and current mitigation.

**Likelihood:** 1 (rare) – 5 (almost certain)  
**Impact:** 1 (negligible) – 5 (critical)  
**Severity:** L × I

---

## 1. Bootstrap Risks

### R-001 — Circular Control Plane Dependency

| Field        | Value |
|--------------|-------|
| Description  | Product provisioning requires a running Control Plane for registration. If the Control Plane is not yet deployed, all product `--provision` runs fail at the registration step. |
| Likelihood   | 3 |
| Impact       | 3 |
| Severity     | 9 |
| Status       | Mitigated |
| Mitigation   | `--profile control-plane` bootstrap is explicitly designed to run without a pre-existing Control Plane. Product registration is a post-provision step that is skippable with `--skip-registration` flag if the Control Plane is not yet live. Registration failure does not roll back infrastructure. |

---

### R-002 — Terraform Provider Availability

| Field        | Value |
|--------------|-------|
| Description  | Supabase, ZITADEL, Fly.io, and Doppler Terraform providers are maintained by third parties and may lag behind API changes or be abandoned. |
| Likelihood   | 2 |
| Impact       | 4 |
| Severity     | 8 |
| Status       | Accepted with mitigation |
| Mitigation   | Pin provider versions; monitor provider GitHub repos for maintenance activity; maintain fallback scripts for each provider that use provider APIs directly via `null_resource` + curl if the provider becomes unusable. Review quarterly. |

---

### R-003 — Supabase Project Limit

| Field        | Value |
|--------------|-------|
| Description  | Supabase free and team tiers have project count limits. Creating four isolated projects per product (dev/test/stg/prod) consumes quota rapidly. |
| Likelihood   | 4 |
| Impact       | 2 |
| Severity     | 8 |
| Status       | Accepted with mitigation |
| Mitigation   | Upgrade to Supabase Pro/Enterprise tier for the KORAS organization. Document minimum tier requirement in `ARCHITECTURE.md`. Confirm quota before provisioning. |

---

## 2. Security Risks

### R-004 — Secret Leak via Generator Output

| Field        | Value |
|--------------|-------|
| Description  | The generator assembles Terraform input variables and Control Plane registration payloads. A bug could cause secret values (DB passwords, API keys) to appear in logs, console output, or committed files. |
| Likelihood   | 2 |
| Impact       | 5 |
| Severity     | 10 |
| Status       | Mitigated |
| Mitigation   | Generator code is reviewed to ensure all Terraform variable assembly uses only non-secret reference values. The `contract.ts` registration type explicitly excludes all `*_key`, `*_password`, `*_secret` fields. Automated test asserts no secret patterns appear in registration payload or dry-run output. `gitleaks` runs on every commit. |

---

### R-005 — Terraform State Exposure

| Field        | Value |
|--------------|-------|
| Description  | Terraform state may contain sensitive values (Supabase service role keys, ZITADEL tokens) if provider outputs are not properly marked `sensitive`. |
| Likelihood   | 3 |
| Impact       | 5 |
| Severity     | 15 |
| Status       | Mitigated |
| Mitigation   | All secret outputs are marked `sensitive = true`. Post-apply provisioners write secrets directly to Doppler rather than storing in state. Remote state backend has encryption at rest and strict IAM access. Audit access to state backend quarterly. |

---

### R-006 — RLS Misconfiguration

| Field        | Value |
|--------------|-------|
| Description  | An incorrect or missing RLS policy on a tenant-scoped table could expose one tenant's data to another. |
| Likelihood   | 2 |
| Impact       | 5 |
| Severity     | 10 |
| Status       | Mitigated |
| Mitigation   | All tenant-scoped tables have RLS enabled by default and are tested in `supabase/tests/`. A CI check confirms `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` is present for every tenant table. New tables without RLS policies trigger a CI failure. |

---

### R-007 — ZITADEL Branding Exposure

| Field        | Value |
|--------------|-------|
| Description  | A misconfigured OIDC redirect or application configuration could land customers on the raw ZITADEL console or login page, exposing KORAS infrastructure branding. |
| Likelihood   | 3 |
| Impact       | 3 |
| Severity     | 9 |
| Status       | Mitigated |
| Mitigation   | All OIDC applications are configured to redirect only to branded login flows. Redirect URIs are allowlisted. Product-branded and customer-branded login UI is built on ZITADEL's branding API. E2E tests assert that no ZITADEL Console URL appears in customer-facing flows. |

---

## 3. Operational Risks

### R-008 — Generated Project Drift from Starter

| Field        | Value |
|--------------|-------|
| Description  | After generation, a product repository diverges from the starter template as both evolve independently. Security patches or architectural improvements in the starter cannot be automatically applied to existing products. |
| Likelihood   | 5 |
| Impact       | 3 |
| Severity     | 15 |
| Status       | Accepted with mitigation |
| Mitigation   | Maintain a documented upgrade guide per starter release. Structure shared packages (`packages/`, `python-packages/`) so they are published as versioned packages and consumed as dependencies, enabling semver-controlled updates. Flag breaking changes in release notes. |

---

### R-009 — Multi-Environment Cost Overrun

| Field        | Value |
|--------------|-------|
| Description  | Four isolated environments per product × multiple products = significant cloud spend (Supabase, Fly.io, Vercel). |
| Likelihood   | 4 |
| Impact       | 2 |
| Severity     | 8 |
| Status       | Accepted with mitigation |
| Mitigation   | `dev` and `test` environments use minimum resources (smallest Fly machine sizes, Supabase free tier where possible). Automated nightly shutdown of `dev` Fly apps when no traffic detected. Monthly cloud cost review. |

---

### R-010 — Terraform Apply Failure Mid-Provisioning

| Field        | Value |
|--------------|-------|
| Description  | A Terraform apply that partially succeeds leaves infrastructure in an inconsistent state (e.g., GitHub repo created, Supabase not). |
| Likelihood   | 3 |
| Impact       | 3 |
| Severity     | 9 |
| Status       | Accepted with mitigation |
| Mitigation   | Terraform remote state tracks what was created. Re-running `terraform apply` is safe (idempotent modules). The generator provides a `--resume` flag for provision runs that resumes from last known state. Manual cleanup guide is documented for unrecoverable states. |

---

### R-011 — ZITADEL Instance Unavailability

| Field        | Value |
|--------------|-------|
| Description  | KORAS maintains four ZITADEL instances. If the production instance is unavailable, all KORAS products lose authentication. |
| Likelihood   | 2 |
| Impact       | 5 |
| Severity     | 10 |
| Status       | Accepted with mitigation |
| Mitigation   | ZITADEL Cloud is deployed in multi-region HA configuration. ZITADEL SLA is 99.9% uptime. Products implement a short-lived JWT cache (5-minute TTL) to handle brief ZITADEL interruptions. Incident runbook documented. |

---

## 4. Delivery Risks

### R-012 — Generator Complexity Underestimated

| Field        | Value |
|--------------|-------|
| Description  | The generator must handle profile-aware templating, Terraform orchestration, interactive prompts, conflict detection, and registration — more complex than a typical scaffolding tool. |
| Likelihood   | 3 |
| Impact       | 2 |
| Severity     | 6 |
| Status       | Accepted |
| Mitigation   | Phase 0 documents fully specify generator behavior before implementation begins. Generator is broken into small, independently testable modules. Each module has unit tests with mocked external dependencies. |

---

### R-013 — Profile Manifest Schema Changes

| Field        | Value |
|--------------|-------|
| Description  | As profiles evolve, the manifest schema changes. Existing generated projects that were generated from an older schema may be incompatible with the new generator. |
| Likelihood   | 3 |
| Impact       | 2 |
| Severity     | 6 |
| Status       | Accepted |
| Mitigation   | Profile manifests are versioned (`schema_version` field). The generator validates the manifest version on load and provides migration tooling for version upgrades. Manifests are treated as semver-versioned contracts. |

---

### R-014 — Control Plane Not Available at Product Registration Time

| Field        | Value |
|--------------|-------|
| Description  | During product provisioning, the Control Plane endpoint may be unreachable (maintenance window, cold start, network issue). |
| Likelihood   | 2 |
| Impact       | 2 |
| Severity     | 4 |
| Status       | Accepted |
| Mitigation   | Registration is a separate, retryable step. Infrastructure provisioning does not depend on registration success. The generator provides a standalone `register` command that can be run independently: `pnpm create-koras-app register --slug docoris`. |

---

## 5. Risk Summary

| ID    | Description                                  | Severity | Status                   |
|-------|----------------------------------------------|----------|--------------------------|
| R-001 | Circular Control Plane dependency            | 9        | Mitigated                |
| R-002 | Terraform provider availability              | 8        | Accepted with mitigation |
| R-003 | Supabase project limit                       | 8        | Accepted with mitigation |
| R-004 | Secret leak via generator output             | 10       | Mitigated                |
| R-005 | Terraform state exposure                     | 15       | Mitigated                |
| R-006 | RLS misconfiguration                         | 10       | Mitigated                |
| R-007 | ZITADEL branding exposure                    | 9        | Mitigated                |
| R-008 | Generated project drift from starter         | 15       | Accepted with mitigation |
| R-009 | Multi-environment cost overrun               | 8        | Accepted with mitigation |
| R-010 | Terraform apply failure mid-provisioning     | 9        | Accepted with mitigation |
| R-011 | ZITADEL instance unavailability              | 10       | Accepted with mitigation |
| R-012 | Generator complexity underestimated          | 6        | Accepted                 |
| R-013 | Profile manifest schema changes              | 6        | Accepted                 |
| R-014 | Control Plane not available at registration  | 4        | Accepted                 |

---

## Review Schedule

This register is reviewed:
- At the start of each implementation phase
- After any security incident
- Quarterly during steady-state operations

New risks are added as they are identified. Resolved risks are marked
`Resolved` with a resolution date rather than deleted.
