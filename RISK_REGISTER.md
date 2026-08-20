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
| R-015 | Terraform plan committed by the generator    | 25       | Resolved                 |
| R-016 | Generated Doppler project left empty         | 12       | Resolved                 |
| R-017 | Control-plane env contract was the product one | 10     | Resolved                 |
| R-018 | Queue polling billed per command             | 8        | Resolved                 |

---

## Review Schedule

This register is reviewed:
- At the start of each implementation phase
- After any security incident
- Quarterly during steady-state operations

New risks are added as they are identified. Resolved risks are marked
`Resolved` with a resolution date rather than deleted.

---

## R-015 — the generator committed a Terraform plan, and with it the estate's credentials

*Severity: critical. Resolved in the generator. Already-generated projects need
rotating, which no change here can do for them.*

`--provision` wrote the Terraform plan to `tfplan` inside the project it had
just created (`src/terraform/runner.ts`), and the next step committed everything
and pushed it (`src/cli/index.ts`, provision at 304 → `initAndPushToDevelop` at
312, `git add .` in `src/git.ts`).

A plan file embeds a **full state snapshot**. Found in one generated project:
four Supabase database passwords and four ZITADEL OIDC client secrets, in
plaintext, in a repository on GitHub.

### Why nothing noticed

The affected project runs gitleaks over its full history and reported nothing.
gitleaks decides whether to look inside an archive from the **file extension**,
and archive traversal is off by default. Terraform names plan files without an
extension.

Measured on the real artifact, not inferred:

| Scanned as | Bytes read | Findings |
|---|---|---|
| `tfplan` | 0 | none |
| `tfplan.zip` (byte-identical) | 214 KB | 28 |

So a secret scanner is structurally blind to precisely the artifact most likely
to carry an entire estate's credentials.

### Why it mattered so much here

The ZITADEL client secret is **generated by ZITADEL and returned into state**.
Nothing was configured to receive it — see R-016 — so Terraform state was its
only home. The committed plan was therefore a copy of the only copy.

### Resolution

Three layers, in descending order of how much they do:

1. **The plan is written to a temporary directory** outside the project and
   deleted after apply, or after a failed apply, or after a declined one. The
   artifact no longer exists in the tree, rather than being hidden there.
2. **Both profile templates ignore** `tfplan`, `*.tfplan`, `*.plan.out`.
3. **`initAndPushToDevelop` refuses to commit** a plan or state artifact, found
   by path, and its message says *rotate*, not merely delete. Checked before
   `git add`, because the commit is pushed moments later.

Generated projects also now carry `tests/security/test_no_state_artifacts.py`,
so each one enforces the rule in its own CI rather than relying on this repo.

Verified by breaking each: putting the plan back in the project takes down nine
tests, removing the commit guard takes down two, dropping the ignore rule takes
down two.

### What this does not fix

Every project generated before this change may carry the same file. Deleting it
does not unpublish anything: **the credentials must be rotated** — Supabase
database passwords and ZITADEL client secrets, per environment, per project.

## R-016 — the generated Doppler project is created empty

*Severity: high. Detection shipped; population is still an operator step.*

`modules/doppler` creates the project and its environments and writes no
values. There is no `doppler_secret` resource anywhere in the configuration.

That omission is **correct**. Writing values through Terraform would put every
credential in state permanently, making state the authority and Doppler a
replica — the inverse of the rule that Doppler is the secret authority, and the
mechanism that made R-015 as bad as it was.

The defect is that nothing filled the gap it leaves and nothing watched it. A
generated project could reach "provisioned" with a completely empty secret
store, and an empty Doppler config is indistinguishable from a correct one until
a service boots and cannot read its settings.

*Resolution* — both profile templates now ship `local/scripts/doppler-check.sh`
and a `make doppler-check` target. It compares the names each config holds
against `.env.local.example`, which is the contract: a setting added to the code
and forgotten in Doppler starts failing the check on its own. It reads **names
only** and never requests a value, so it is safe to run in CI.

Populating the values remains an operator step, deliberately. A script that
writes secrets is a script that must receive them, which puts them in shell
history and process arguments.

## R-017 — the control-plane profile shipped the product environment contract

*Severity: medium. Resolved.*

`profiles/control-plane/template/local/config/.env.local.example.hbs` differed
from the product one by two lines. It shipped `MINIO_ROOT_PASSWORD`,
`LITELLM_MASTER_KEY`, `AI_GATEWAY_URL`, `CONTROL_PLANE_URL` and
`CONTROL_PLANE_API_KEY` — a storage stack the profile does not include, an AI
gateway it does not run, and a client credential for *itself*, which invariant 2
forbids outright.

The corrected contract existed, but only in one generated project where someone
had fixed it by hand. That is R-008 made concrete: a fix applied downstream and
never pushed back, so every regeneration would undo it.

*Resolution* — the corrected contract is now the template, with ports
re-templatised. The two tools that read it (`doppler-check.sh`,
`doppler-bootstrap.sh`) would otherwise have demanded a control plane register
itself as a client of itself.

## R-018 — the queue polled 170,000 times a day with nothing to do

*Severity: low, but it is money. Resolved.*

arq's `poll_delay` defaults to 0.5 seconds and no profile overrode it. That is
two Redis commands per second per worker, continuously, whether or not there is
work: roughly 170,000 a day per worker, ~21 million a month across four
environments, on an entirely idle platform.

Against a managed queue billed per command that is a real line item for doing
nothing, and it exhausts a serverless free tier within minutes of the worker
starting — a failure that looks like a broken queue rather than a spent quota.

*Resolution* — `poll_delay = 5.0` in both worker templates, pinned by a test in
the generated project. Nothing here needs sub-second pickup: provisioning is a
multi-minute operation a person triggers, and reconciliation runs on a
fifteen-minute timer.

## On the Upstash module

`modules/upstash` creates one Redis database per environment. One each, never
one shared with a key prefix: a prefix is a convention, and the rule that a dev
process may not touch a prod resource cannot rest on a convention. Separate
databases mean separate credentials, so a dev worker holding a prod queue URL is
a mistake someone made rather than an accident waiting in a shared namespace.

`eviction = false`, and it must stay false. This is a job queue: an evicted key
is a provisioning job that vanishes silently, leaving a customer half-onboarded
with nothing recording that anything was lost.

The connection URL embeds the password, so `redis_urls` is sensitive and reaches
Doppler through the bootstrap. Terraform state holds a copy because the provider
returns one and there is no way to ask it not to — the same shape as the ZITADEL
client secret, and the reason the plan file mattered so much.

## On finding the derivation bug by running it

The secrets manifest first had two columns, name and class, and the bootstrap
looked each `derived` setting up in the Terraform outputs *by its own name*.
Those names are not the same: `ZITADEL_PROJECT_ID` comes from an output called
`zitadel_project_ids`. Every lookup missed, every derived value silently fell
back to a prompt, and the whole feature did nothing while appearing to work.

A dry run could not show it — everything said "would ask", which is what an
unpopulated Doppler looks like anyway. It appeared only when the lookup was
tried against real outputs pulled from a real state file. The manifest now
carries an explicit SOURCE column, and a generated-project test fails if a
derived setting lacks one.
