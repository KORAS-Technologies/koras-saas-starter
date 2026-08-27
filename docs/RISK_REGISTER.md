# KORAS SaaS Starter — Risk Register

## Overview

This register tracks identified risks to the delivery and operation of the
`koras-saas-starter` and its generated projects. Each entry includes a
likelihood rating, impact rating, overall severity, and current mitigation.

**Likelihood:** 1 (rare) – 5 (almost certain)  
**Impact:** 1 (negligible) – 5 (critical)  
**Severity:** L × I

**These numbers are local to this repository.** `koras-control-plane` keeps its
own register in the same `R-NN` shape, and the two have long since overlapped:
R-05 there is a cross-organization read in the platform schema, R-05 here is
something else entirely. When citing one across repositories, say which —
"control-plane R-65", "starter R-028" — because the bare number identifies two
different defects depending on which register the reader opens.

The same is true of phase numbers: Phase 12 is Security here and "Domains and
branding" there.

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
| Mitigation   | `--profile control-plane` bootstrap is explicitly designed to run without a pre-existing Control Plane. Product registration is a post-provision step that is skippable with `--skip-registration` if the Control Plane is not yet live. Registration failure does not roll back infrastructure. |
| Verified     | 2026-08-25, Phase 10. The flag exists and is honoured; an absent `KORAS_CONTROL_PLANE_URL` is treated as the documented bootstrap order and skips rather than fails; a registration failure prints the retry command and unwinds nothing. Asserted in `registration-client.test.ts` and `tests/e2e/product-provision.test.ts`. Until this date the mitigation described a flag nobody had implemented. |

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
| R-030 | Every CI gate had never run                  | 20       | Resolved                 |
| R-032 | RLS enforced against nobody (owner + superuser) | 20     | Resolved                 |
| R-033 | Token checks loosest on external input       | 9        | Resolved                 |
| R-034 | No rate limiting in the generated API        | 12       | Resolved                 |
| R-035 | `pnpm test` reported a cached pass           | 16       | Resolved                 |
| R-031 | vitest advisories; the fix breaks the suite  | 12       | Accepted with mitigation |
| R-036 | A live acceptance run cannot be cleaned up   | 12       | Unverified against providers |
| R-037 | Typecheck ignored the error it needed to report | 12    | Resolved                 |
| R-038 | Drift reported every optional component      | 9        | Resolved                 |
| R-039 | ZITADEL module could not create a new project | 16      | Resolved                 |
| R-040 | Teardown missed a whole provider silently    | 16       | Resolved                 |
| R-041 | Teardown made the operator write secrets to disk | 20   | Resolved                 |
| R-042 | Prose is the only untested part of the repository | 12  | Partly closed            |
| R-016 | Generated Doppler project left empty         | 12       | Resolved                 |
| R-017 | Control-plane env contract was the product one | 10     | Resolved                 |
| R-018 | Queue polling billed per command             | 8        | Resolved                 |
| R-019 | ZITADEL projects defined no roles            | 20       | Resolved                 |
| R-020 | Nothing carried settings into the runtime    | 20       | Resolved                 |
| R-021 | Applications had no hostnames                | 16       | Resolved                 |
| R-022 | The doctor passed a token that could not write DNS                     | 8        | Resolved                 |
| R-023 | Every Vercel project named a package that cannot exist                 | 12       | Resolved                 |
| R-024 | Deployed services never received ENVIRONMENT                           | 20       | Resolved                 |
| R-025 | A JSON setting arrived escaped, and a --cwd was ignored                | 16       | Resolved                 |
| R-026 | A green deploy left the worker and scheduler stopped                   | 16       | Resolved                 |
| R-027 | The applications had no settings, and two projects could not hold four | 20       | Resolved                 |
| R-028 | Two estates claimed the same hostnames                                 | 20       | Resolved                 |
| R-029 | A redundant depends_on made one environment's roles unapplyable        | 6        | Resolved                 |

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

## R-019 — the identity projects defined no roles

*Severity: critical. Resolved.*

The ZITADEL module created a project and an OIDC application and stopped.
`project_role_assertion` was already true, so a caller's roles would be written
into the `urn:zitadel:iam:org:project:roles` claim — but a project with no roles
defined can grant none, so every token arrived with an empty claim.

The failure is silent and complete. Sign-in succeeds. The session is valid. The
middleware reads no role and refuses every page. A perfectly provisioned,
perfectly deployed platform that nobody can log into, and nothing in the
provisioning output hints at why.

*Resolution* — `zitadel_project_role` for each role the code parses, chosen by
profile: the five `platform_*` roles for a control plane, the five organization
roles for a product. A product gets no platform roles at all — staff authority
lives in one place, and issuing `platform_admin` from a product project would
create a second.

`org_id` is set explicitly from the project. Unlike the project and application
resources the provider does not resolve it here, and a role created in a
different organization than its project is accepted by the API and never appears
in anyone's token.

## R-020 — nothing carried settings from Doppler into the running services

*Severity: critical. Resolved.*

Doppler holds the values. The containers read them from their environment.
Nothing connected the two — not Terraform, not the deploy workflow. A deployment
would have completed, and every service would have failed settings validation on
a missing `ENVIRONMENT` and crash-looped.

Found while reviewing what the starter provisions rather than by running it,
which is the only reason it was found before someone tried to deploy.

*Resolution* — the deploy workflow downloads the environment's settings and
stages them with `flyctl secrets import` before the deploy, so the new release
starts with the settings it expects in one restart rather than two.
`--no-file` keeps the values on the pipe: writing them to a shared runner's
workspace leaves them for anything that reads it.

The whole deploy pipeline was shipped upstream at the same time. The templates
still carried the version that ran `turbo run build` and stopped — a green check
on every push meaning "the code compiles" while claiming to mean "the code is
live". That had been fixed in one generated project and never pushed back.

### On why deploy.yml is not a Handlebars template
It is copied verbatim. The file is dense with GitHub `${{ ... }}` expressions,
and Handlebars parses those: making it a `.hbs` replaced
`${{ secrets.FLY_API_TOKEN }}` with an empty string and produced a workflow that
looked correct and authenticated as nobody. Sixty-four tests failed at once,
which is the good version of that discovery. The app name is built from
`github.event.repository.name` instead, which equals the project slug.

## R-021 — the applications had no hostnames, so sign-in ended on NXDOMAIN

*Severity: high. Resolved.*

The Vercel module created `vercel_project` and nothing else, and the Cloudflare
module was wired with `dns_records = []` behind a comment saying records were
"assembled from Vercel and Fly outputs post-apply". Nothing ever assembled them.

A Vercel project with no domain answers only on its generated `*.vercel.app`
name. Everything else in the estate was configured for the real hostnames — the
OAuth redirect URI registered in ZITADEL, `NEXT_PUBLIC_ADMIN_URL`,
`CORS_ORIGINS` — so the flow was: sign in, succeed, get redirected to
`admin-dev.<domain>`, and land on a name that resolves to nothing.

Everything up to that point looks healthy, which is what makes it expensive: the
identity provider is fine, the token is valid, the application is deployed, and
the only broken thing is a DNS record nobody created.

*Resolution* — `vercel_project_domain` attaches one hostname per application per
environment, and `project-bootstrap` feeds those domains to Cloudflare as CNAME
records.

Three decisions worth keeping:

- **Non-production domains are bound to a branch.** Vercel deploys every branch
  as a preview, and without the binding `admin-dev` follows whichever deployment
  was most recent — including one from an unrelated branch. Production is
  deliberately *not* bound: a `git_branch` there would pin it and stop `--prod`
  moving it.
- **CNAME, not A.** Vercel's edge addresses change, and a pinned address is an
  outage nobody causes and nobody expects.
- **Not proxied through Cloudflare.** Vercel terminates TLS for the domain
  itself; proxying puts a second certificate in front of a valid one, which
  fails until Vercel has issued and then serves the wrong chain.

The API is deliberately absent from DNS. It answers on its Fly hostname, which
is what the settings already point at, so a record here would be a second name
for something reachable and a second thing to keep correct.

### On authenticating to a hosted collector
`OTEL_EXPORTER_OTLP_HEADERS` is now in both manifests. Nothing in the codebase
reads it: the OpenTelemetry SDK picks it up from the environment on its own,
which was measured rather than assumed. So Grafana Cloud and similar need no
code change — only the value, in the form `authorization=Basic <base64>`.

An empty `OTEL_EXPORTER_OTLP_ENDPOINT` remains a valid answer, and the right one
until a collector exists: the tracing setup treats it as "no exporter", so spans
are still created and trace context still crosses the queue.

### On a chicken and egg between domains and deployments
The first version of R-021 attached every domain, branch-pinned ones included,
in one apply. Six of eight failed:

    git_branch_not_found - Branch "develop" not found in the connected Git
    repository.

The branch existed on GitHub and the Vercel GitHub App was installed for the
organisation. What was missing is subtler: **Vercel learns a repository's
branches from deployments**, not from the Git provider, and neither project had
ever deployed. So the domains wanted a deployment, and the deployment is what
the pipeline does after provisioning.

The two production domains attached fine -- they need no branch -- and because
the DNS records derive from the whole set, a partial failure left sixteen
hostnames configured and zero records created.

*Resolution* — production and branch-pinned domains are now separate resources,
and the branch-pinned set is behind `attach_branch_domains`, default **false**.
A fresh estate provisions cleanly with production domains, deploys, and then
turns the flag on. Defaulting it true would mean every new project fails its
first apply on something that is not wrong.

The DNS records follow whichever domains were actually attached, so the two
states are always consistent: a hostname with no record is unreachable, and a
record with no hostname points at Vercel for a domain it will not serve.

## R-022 — the doctor reported Cloudflare ready for a token that could not write DNS
*Severity: medium. Resolved.*

`bootstrap:doctor` printed `Cloudflare ✓` and the apply then failed on the first
record with `Authentication error (10000)`.

The check read the zone. That proves the token can *see* the zone and nothing
more: a token holding `Zone:Read` alone passes it. Probing the real token showed
exactly that split -- zone read `200`, DNS records `403`.

Same shape as every other defect this week. A check that answers a question
adjacent to the one that matters reads as reassurance, and the operator finds
out during an apply instead.

*Resolution* — the check now also lists one DNS record. Still read-only, still
cheap, and it distinguishes `Zone:Read` from a token with DNS scope. It does not
prove `Edit`, and the message and the runbook both say so: proving that means
writing a record, and a doctor that creates DNS in a production zone is a doctor
nobody runs before a production apply.

## R-023 — every Vercel project carried a build command naming a package that cannot exist

*Severity: high. Resolved.*

`build_command` defaulted to a string containing unsubstituted upper-case
placeholders for the project slug and the application name. Nothing ever
replaced them, and nothing overrode the variable, so the default reached the
real Vercel project unchanged.

It fails only at the first deployment, long after provisioning reports success:

    No package found with name '<placeholder>' in workspace

*Resolution* — the command is derived per application from the workspace package
name, and `build_command` now defaults to null meaning "derive it". A single
shared string could never be right for more than one application, which is the
deeper reason the placeholder survived: there was no correct value to put there.

The package name comes from the **source directory**, not the component key.
`platform_admin` lives in `apps/admin` and is published as `@slug/admin`;
deriving from the key would name a package nothing publishes.

### On a comment that defeated its own check
The first version of this fix explained itself by quoting the old placeholder
verbatim, and the test that forbids that literal failed on the comment. Reworded
rather than weakened: a check that forbids a string is defeated by any text
repeating it, which is worth knowing before writing the next such check.

## R-024 — deployed services never received ENVIRONMENT

*Severity: high. Resolved.*

Reproduced from a crash-looping Fly machine: the API exited on startup with
`ValidationError: environment Field required`. Every setting reached the
container except the one with no default.

`secrets.manifest` classified `ENVIRONMENT` as `local`, reasoning that it is set
per Doppler config rather than stored in it. That is true of the local stack and
false of everything deployed: a service reads its settings from the environment,
not from Doppler's notion of which config they came from. So `doppler-check`
never asked for it, `doppler secrets download` never produced it, and all three
services crash-looped while the deployment reported success.

The setting has no default in code on purpose -- a missing or misspelled value
must stop a process rather than silently select an estate (R-03) -- which is
exactly why leaving it out is fatal rather than merely untidy.

*Resolution* -- a third manifest source, `self:environment`, resolving to the
environment's own name. It is derived, so the bootstrap writes it, the checker
verifies it and the deploy carries it. `OTEL_EXPORTER_OTLP_PROTOCOL`, which
existed only in the generated Control Plane and not in the templates, shipped
alongside.

The generation test rejected the new source kind as unrecognised, which is the
test working: it forbids a derived setting with no usable source. Widened
deliberately rather than by reflex.

## R-025 — a JSON setting arrived escaped, and a --cwd was silently ignored

*Severity: high. Resolved.*

Both from the first deployment that actually reached the services.

The API crash-looped on:

```text
SettingsError: error parsing value for field "cors_origins"
JSONDecodeError: Expecting value: line 1 column 2 (char 1)
```

`doppler secrets download --format env` renders a JSON value with the inner
quotes escaped. flyctl strips the outer quotes and leaves the backslashes, so
the service receives text no JSON parser accepts -- and column 2 is exactly
where the first backslash sits. Confirmed by rendering both formats:
`env-no-quotes` emits the array cleanly.

Separately, the Vercel step passed `--cwd apps/<app>` while the project already
carried `root_directory=apps/<app>`, so Vercel looked for the path twice over,
warned that it did not exist, and ignored the setting rather than failing. A
warning nobody reads is indistinguishable from a setting that worked.

*Resolution* -- `env-no-quotes` for the download, and the Vercel step runs from
the repository root so the project's own `root_directory` applies once.

## R-026 — a green deploy left the worker and scheduler stopped

*Severity: high. Resolved.*

The first fully green deployment shipped all three services, and the Fly
dashboard showed one app deployed and the other two idle. Their machines had
been created, updated, and never started: the event history reads
`launch created` → `update stopped`, with no `start` and no `exit`.

The API was unaffected because its `http_service` gives Fly a reason to start
it. The worker and scheduler declare a process group and no service, and
`flyctl deploy` returned success having left every machine down.

So the pipeline reported a successful release while nothing consumed the queue.
That is precisely the failure this pipeline was built to stop reporting as
fine, arriving one layer deeper than the last time: not a deploy that ships
nothing, but a deploy that ships and does not run.

Confirmed rather than inferred: starting one worker machine by hand brought it
up and it stayed up. The image, the settings and the code were all correct.

*Resolution* — the deploy now starts anything not already started and fails if
any machine remains stopped. `--ha=false` too: Fly's default created two
machines per app, which for the scheduler is actively wrong -- two of them
enqueue every sweep twice, and the audit log records two runs where one
happened.

## R-027 — the applications had no settings, and two projects could not hold four

*Severity: high. Resolved.*

The admin app answered 500 on its own sign-in route. Its Vercel project held
zero environment variables: settings were pushed to Fly and nowhere else, so
`ZITADEL_DOMAIN` was empty, the authorize URL came out relative, and the
redirect threw. The same gap the services had, one surface over.

Fixing it exposed a structural problem rather than a second oversight. A Vercel
project has three environment-variable targets -- production, preview,
development -- not one per estate. Isolating four environments inside one
project therefore needs preview variables scoped per git branch, and Vercel
learns a repository's branches only from git-triggered deployments. These deploy
from CI with the CLI, so it never learns them: every scoped call failed with
`Branch "develop" not found in the connected Git repository`.

The alternatives were one working application environment, or a shared non-prod
configuration in which a staging deployment reads dev's database and dev's
identity provider -- a cross-environment read, and the browser tier being the
one place the four-environment model stopped.

*Resolution* — one project per application per environment. Eight rather than
two, matching four Supabase projects, four ZITADEL instances and twelve Fly
apps. Each project is a single estate, so its own production target holds that
estate's settings and its own domain points at it. Nothing needs to know what a
branch is, which is why `attach_branch_domains` is gone: the flag existed only
to defer domains that cannot be created before a project has deployed, and
there are no such domains now.

The deploy pushes the environment's settings into its project before building --
before, because the build reads `NEXT_PUBLIC_*` at build time -- and deploys
with `--prod` in every environment, because production here means this
environment's own project.

### Migrating an estate that already has two
`for_each` is re-keyed, so Terraform proposes destroying the two existing
projects and creating eight. Both carry `prevent_destroy`, so it will refuse
rather than do it. Move the two production ones into their new addresses first:

    terraform state mv       'module.bootstrap.module.vercel.vercel_project.apps["platform_admin"]'       'module.bootstrap.module.vercel.vercel_project.apps["platform_admin-prod"]'

and the same for the portal, plus their `vercel_project_domain` entries. The
plan then reads as six creates and two in-place renames.

### On a test that passed while the thing it guarded was reverted
The first version asserted the module *mentioned* `project_matrix`. Reverting
`for_each` to one project per application left every one of those strings in
place and the test still passed. It now reads the resource block and asserts
what it iterates.


---

## R-028 — two estates claimed the same hostnames, and the second one lost

*Severity: high. Resolved in the factory (03d260b); the estates still need re-applying.*

`sample-product` could not attach four of its eight application domains:

```text
Could not add domain admin-dev.korastechnologies.com to project
prj_b3dKdLoCaQL48qFrTdj4O4KzrKjR, unexpected error: domain_already_in_use
```

`koras-control-plane` holds `admin`, `admin-dev`, `admin-test` and `admin-stg`
on `korastechnologies.com`, and `account*` beside them. The product wanted the
same four names.

The labels are not the fault. The vercel module maps the Control Plane's
`platform_admin` to `admin` deliberately, and the product's `admin` key falls
through to itself -- also `admin`. Both are right in isolation. `web` mapped to
`app` and succeeded only because nothing else wanted that name.

What is wrong is that they are in the same namespace at all.
`INFRASTRUCTURE_PLAN.md` specifies `primary_domain` as a per-project input --
its worked example is `"primary_domain": "docoris.app"` for a product. The
implementation reads it from `TF_VAR_primary_domain` in the shared
`koras-platform-bootstrap` Doppler config, which holds one value for the whole
estate. So every project the factory produces lands on the same apex.

That makes the collision structural rather than particular to this pair. A
second product collides with the first on `app` and `admin` on its first apply,
and the failure arrives late: eight Vercel projects are created, four domains
attach, and the apply dies partway with half the estate in place.

It also reached further than Vercel. `redirect_uris` and the Cloudflare records
are both derived from `module.vercel.domains`, so an incomplete domain map left
the OIDC callbacks and the DNS records unbuilt in the same run. A hostname
conflict presents as an identity and DNS outage.

*Resolution* — `primary_domain` is now a per-project value carried in
the generated `terraform.tfvars`, which is committed and non-secret and is where
`INFRASTRUCTURE_PLAN.md` always said it belonged. A product defaults to
`<slug>.<estate apex>`; the Control Plane keeps the apex, because it is the
platform. `application_hostnames` and the `admin_urls` output need no change:
once the namespace is per project, `admin.<slug>.<apex>` and
`admin.<apex>` cannot meet.

The bootstrap Doppler value stays, reinterpreted as the estate apex the
generator composes from rather than the domain any one project uses.

## R-029 — a redundant depends_on made one environment's roles unapplyable

*Severity: low. Resolved (03d260b).*

Every ZITADEL instance consumes `local.redirect_uris`, which reads
`module.vercel.domains`, so all four already depend on the Vercel module through
the values they use. `module "zitadel_dev"` additionally declares
`depends_on = [module.vercel]`, and its three siblings do not.

An explicit module-level `depends_on` applies to every resource in the module,
not only the ones that read the value. `zitadel_project_role` reads no redirect
URI, so in `test`, `stg` and `prod` the roles could be created while the Vercel
module was refusing an unrelated destroy. In `dev` they could not: the blanket
dependency pulled the whole module in, including its errors.

The effect was that the one environment in daily use was the one that could not
receive its roles, and the reason was invisible -- the plan simply omitted them.

*Resolution* — the explicit `depends_on` is gone. The implicit
dependency is real, narrower, and already correct.

## R-030 — every CI gate in the roadmap has never run

**Found:** 2026-08-24, while checking whether the newly-working `pnpm lint`
turned the CI job green.

It could not have. The **CI**, **Generator Integration** and **Security**
workflows have `total_count: 0` recorded runs each. Not failing runs — none at
all, across 85+ commits on `develop`, with all three registered and `active`
and repository-level Actions reporting `{"enabled": true, "allowed_actions":
"all"}`.

**Why this matters more than a red build.** A failing job is visible and gets
fixed. A job that never runs looks identical to a job that has nothing to say,
and every process built on top of it inherits a confidence it never earned:

- Phase 11's exit criterion is "all starter CI workflows pass". Zero runs pass
  vacuously if read carelessly and cannot be evaluated if read carefully.
- Phase 12's is "zero critical/high findings in automated scans". No scan has
  executed, so the finding count is zero for the wrong reason.
- Branch protection that requires a check GitHub never reports either blocks
  every merge or, if the check is not marked required, waves everything
  through. `befa163` ("Require the checks GitHub actually reports") suggests
  this was already met from the other direction.

**Compounding it:** until 2026-08-24 the lint script could not have succeeded
anywhere. `eslint` was named in two packages' `"lint"` scripts but was not a
dependency of any workspace package and no config existed, so `pnpm lint`
failed on a clean checkout. That is fixed; it was necessary and nowhere near
sufficient.

**Cause, confirmed 2026-08-25:** Actions billing. GitHub states it on the run
itself:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased.

The earlier guess in this entry -- an organization-level Actions policy -- was
wrong, and so was a second guess that repository-level permission state had
gone stale. The behaviour is explained entirely by visibility and billing:

| Repository | Runs created | Jobs execute |
|------------|--------------|--------------|
| private (before) | no | -- |
| public | yes | **yes** -- executed and found four real defects |
| private (again) | yes | no -- blocked on billing |

Public repositories get Actions minutes free; private ones consume paid minutes,
and this account's payment is failing. Making the repository public is what let
CI run at all; making it private again re-blocked it.

**What the working window bought.** While public, CI ran for the first time and
failed on four things that had been true for as long as the workflows existed: a
pnpm version declared twice so every Node job died before installing, 75 ruff
errors, a mypy invocation that aborted before checking anything, and the AI
gateway's bind-all. All four are fixed in `5c919a8`, verified locally. **CI has
not verified them** -- the run for that commit never started a job.

**Mitigation:** resolve Actions billing -- Settings, then Billing & plans; the
symptom is a failed payment or a spending limit at zero. Alternatives are
keeping the repository public, which trades the licensing position on vendored
third-party skills for free minutes, or a self-hosted runner, which consumes no
minutes and costs setup instead.

**Resolved 2026-08-25.** Jobs execute. The repository is public, so Actions
minutes are free and the billing failure that blocked every private-repo run no
longer applies. Observed rather than inferred — CI run `32805340999` on
`develop` started four jobs and all four succeeded:

| Job | Result |
|-----|--------|
| Lint & Typecheck | success |
| Test (Node) | success |
| Test (Python) | success |
| Build | success |

Security and Generator Integration are green on the same commit, and
Generator Integration ran both profiles.

**The trade this rests on is unchanged.** Free minutes come from the repository
being public, which is the licensing position on the vendored third-party
skills that this entry originally weighed against it. Making the repository
private again re-blocks every run until the Actions billing failure is settled.
If that happens, this risk reopens rather than being rediscovered.

**Consequence for the roadmap:** every CI-based exit criterion is now
measurable. Phase 11's is met. Phase 12's was measurable and *failing* — the
first scan to actually run reported three open high-severity CodeQL alerts,
which is the finding count the criterion asks about and which nobody could have
seen while no scan executed. They are fixed in the commit that resolves this
entry.
`ci.yml` now carries `workflow_dispatch`, so the check costs one manual run
rather than a commit.

## R-031 — the fix for three critical advisories breaks the test suite

**Found:** 2026-08-25, acting on Dependabot's report of seven open advisories
(3 critical, 1 high, 3 moderate) against the default branch.

All seven are one chain. `vitest` is the only direct dependency; `vite` and
`esbuild` arrive under it and are declared nowhere, so there is no range to bump
and they need an explicit `overrides` entry.

| Package | Installed | Patched |
|---------|-----------|---------|
| `vitest` | 2.1.9 | 3.2.6 |
| `vite` | 5.4.21 | 6.4.3 |
| `esbuild` | 0.21.5 | 0.25.0 |

**The upgrade works and cannot be shipped.** With `vitest@3.2.7`,
`vite@7.3.6` and `esbuild@0.28.2`, all 623 tests pass -- but vitest reports five
unhandled `[vitest-worker]: Timeout calling "onTaskUpdate"` errors and **exits
1**, so `pnpm test` fails. Every frame of those errors is inside vitest's own
RPC and timer code; none is in this repository.

The cause is synchronous blocking. Workers here spend long stretches inside
`execFileSync`, `readdirSync` and `rmSync` -- `generated-builds.test.ts` blocks
for roughly 175 seconds installing dependencies and running a Next build -- and
a worker that is blocking the event loop that hard cannot answer the reporter's
RPC. vitest 2 tolerated it; 3 does not.

Two things were tried and did not fix it. `maxWorkers: 4` left the count at
five, which also disproves parallel contention as the explanation. Excluding
`generated-builds.test.ts` reduced it to two, so the blocking is spread across
several files rather than isolated to one.

vitest exposes no RPC timeout setting. It exposes
`dangerouslyIgnoreUnhandledErrors`, which suppresses every unhandled error
including real ones, and is not a fix.

**Why this is not urgent, despite the severity labels.** Read what the
advisories actually require:

- `vitest` (critical) -- "when Vitest **UI server** is listening". This
  repository runs `vitest run`, headless. `--ui` is never passed.
- `vite` (high) -- `server.fs.deny` bypass, requires the **Vite dev server**.
  Never started; the generated Next applications use Next's own dev server.
- `esbuild` (moderate) -- lets any website reach the **development server**.
- `vite` (moderate x2) -- dev-server path traversal, and launch-editor UNC
  handling.

Every one needs a development server listening. None runs here.

They are also confined to this repository: `vitest`, `vite` and `esbuild`
appear in no profile template, so no generated project and nothing deployed
carries them. The blast radius is the starter's own test toolchain.

**Mitigation:** left on `vitest@2.1.9`, deliberately, with the advisories open.
Closing them properly means converting the synchronous filesystem and
child-process work in the test suite to its async equivalents so workers stop
blocking the event loop, then upgrading. That is a real piece of work and worth
scheduling; it is not worth pushing through a change that makes `pnpm test`
exit 1.

Revisit if any of these ever reaches a generated project, if anyone starts
running `vitest --ui`, or once the suite no longer blocks its workers.

**Updated 2026-08-25 — eight alerts, not seven.** Phase 13 added
`tests/e2e/package.json`, which declares `vitest`, so Dependabot opened a fourth
row for the same critical advisory. It is a new *location* of an accepted
finding rather than a new vulnerability: four manifests now declare the
dependency, and all four resolve to the one workspace copy.

The upgrade got harder in the same commit rather than easier. The suite is now
807 tests across three packages, and `tests/e2e` blocks its workers the same way
the others do — it generates two full projects and walks their output on disk.
Whatever async conversion closes this has one more package to cover.

**This is what keeps Phase 12's exit criterion open on a strict reading**, and
that reading is worth stating rather than resolving quietly. The criterion says
"zero critical/high findings in automated scans". CodeQL reports zero. Dependabot
reports four critical and one high, every one of them requiring a development
server that is never started, in a toolchain no generated project carries.

The roadmap now names CodeQL explicitly and records these as accepted here,
because a criterion that can be read two ways gets read the flattering way
later — and "zero findings" while eight alerts are open is exactly the sentence
that would be quoted back.

**Attempted again 2026-08-25, and it is worse than recorded above.** The
upgrade was carried out in full — `vitest@3.2.7`, with `pnpm.overrides` forcing
`vite@7.3.6` and `esbuild@0.25.12`, since vitest 3 accepts the vulnerable vite 5
and pnpm keeps it otherwise. The lockfile came out clean of all three
advisories.

The suite did not. The note above says every test passes and vitest merely exits
1 on unhandled errors; that is no longer true. **18 tests fail**, in the four
files that make the most synchronous filesystem calls:

| Configuration | Failed | Errors |
|---------------|--------|--------|
| default | 18 | 5 |
| `--maxWorkers=2` | 5 | 3 |
| `--no-file-parallelism` | **4** | 3 |

None of the failures is real: every one passes when its file is run alone. The
blocked worker misses the `onTaskUpdate` RPC, vitest 3 tears the worker down,
and reports whatever it was running as failed. Reducing parallelism reduces the
count and never reaches zero, which rules out contention and leaves the
blocking itself.

The RPC timeout is birpc's 60-second default, handed in by the pool. It is not
reachable from vitest config — confirmed by reading `createRuntimeRpc` in
3.2.7, where `onTimeoutError` is defined and the timeout arrives in `options`.

**What closing it would actually cost, which the note above understates.** The
blocking is not in test helpers. It is in `writeFiles()` — the generator's own
synchronous write path, which the tests call exactly the way production calls
it. Making the workers responsive means making that path async, changing
`create-koras-app`'s internals and every call site, to clear advisories that
each require a development server this repository never starts.

The upgrade was reverted. This remains the right call, and it is now backed by
having done it rather than by having estimated it.

---

## R-032 — row-level security was enforced against nobody

**Severity:** 20 (likelihood 4 × impact 5) · **Status:** Resolved 2026-08-25

Every table in both profiles ran `alter table … enable row level security` and
none ran `force`. `enable` does not apply to the table's owner, and both the
migrations and the FastAPI service connect as the owner through the same
`DATABASE_URL`. Every policy in `00002_rls_policies.sql` was correct, present,
and never consulted by the connection that serves tenant traffic.

The `require_tenant` dependency still scoped queries in application code, so
this was not an open door on its own — it was the removal of the second of two
layers, and the second layer exists precisely because the first is application
code and application code is what forgets. Tenant isolation was resting on one
layer while appearing to rest on two.

**Why nothing caught it.** It has no symptom. A developer testing by hand
connects as the owner, sees every policy behave correctly — because the owner
sees everything either way — and concludes the policies work. A test suite
written the obvious way connects the same way and agrees. It fails open, and it
fails open in the direction of cross-tenant reads.

**Resolution:** `force row level security` on all eight tables across the two
profiles. `rls-enforcement.test.ts` fails if a table ever enables RLS without
forcing it, and `supabase/tests/010_rls_structure.sql` fails against a live
database for the same reason. The runner creates a `nobypassrls` role and
`SET ROLE`s into it, because a suite run as the owner passes while proving
nothing.

**Executed 2026-08-25, and `force` alone turned out to be insufficient.**

The suite above had never been run when this entry was first written. Running
it against a real Postgres 16 confirmed the fix, then found what the fix does
not cover.

`force row level security` binds the table's **owner** to its policies. It does
nothing to a **superuser**, and nothing to a role holding **BYPASSRLS** — both
bypass unconditionally, forced or not. Measured rather than reasoned about, with
two tenants and the context set to one:

| Connecting role | `force` | Rows visible |
|-----------------|---------|--------------|
| superuser | ON | **2 — bypassed** |
| non-superuser owner | ON | 1 — isolated |
| non-superuser owner | OFF | **2 — bypassed** |

The middle row is the fix working. The top row is the one that matters: a
managed Postgres commonly issues a superuser as its default connection role, and
a `DATABASE_URL` copied from a dashboard is usually that role. Such a deployment
has correct policies, `force` on every table, a passing policy suite, and **no
row-level security at all**.

The original claim here — that `force` is "what makes layer 2 real" — was half
the answer. Two conditions are required and only one lives in a migration:

1. `force row level security` on every table. Done, and asserted.
2. The application connects as a role that is neither a superuser nor
   BYPASSRLS. **No migration can address this**: it is a property of the
   credential, not of the schema.

**Resolution for the second.** `assert_rls_enforced` in `koras-database` reads
`pg_roles` for the connecting role and raises `RlsNotEnforced` if it is a
superuser or holds BYPASSRLS. `verify_rls_enforcement` calls it from the API
lifespan, before anything is served: the service refuses to start rather than
serving with inert policies, because the alternative is learning about it from
whoever saw another tenant's rows.

The structural suite checks the same when told which role to check
(`-v app_role=<role>`, or `RLS_APP_ROLE` through the runner). Unset, it skips
rather than guesses — the suite runs as a privileged role and cannot infer the
application's.

**The suite is not vacuous, and that was tested rather than assumed.** Removing
`force` from the three tables makes it exit 3 with `RLS is enabled but not
forced on: tenant_members, tenant_settings, tenants`; pointing the role check at
`postgres` makes it exit 3 with `the application role postgres bypasses RLS
(superuser=t, bypassrls=t)`. Both mutations were run and both were caught. The
behavioural suite passes against a database built from freshly generated
migrations — reads, writes, and an unset context failing closed.

**A regression, introduced by this entry's own fix and caught by executing it
on the other profile.** `force row level security` was applied to both profiles
uniformly. The Control Plane must not have it.

Its five tables carry RLS with **no policies at all**, and that is deliberate:
there is no tenant model here, no `current_tenant_id()`, and authorisation is
by platform role in the API through `PlatformAuthDep`. RLS-with-no-policies is
a deny-by-default backstop — everything that is not the service role reads
nothing, and the service role bypasses.

`force` binds the *owner* to the policies. With no policies, that denies the
owner too:

| Role | Before `force` | After `force` |
|------|----------------|---------------|
| service role (bypasses) | reads | reads |
| owner / non-bypassing | 0 rows | 0 rows |

Measured on a real database, the owner returns nothing either way — but paired
with `verify_rls_enforcement`, which refuses to start on a bypassing
connection, the combination is a lock-out: the API refuses the connection that
works, and the connection it demands reads nothing.

**Resolution.** `force` removed from the control-plane schema, with the reason
recorded in its own migration. `require_rls_enforcement` is a setting — `True`
for a product, `False` for the Control Plane — so the startup guard asserts the
product's rule only where the product's arrangement holds. The structural suite
takes `-v deny_all_by_default=1`, under which it skips the force check, reports
the deny-all tables by name as declared rather than failing, and skips the
`current_tenant_id()` check for a schema that scopes no rows by tenant.

**What this says about the original fix.** "Enable RLS, force it, connect as a
non-bypassing role" is right for a schema whose policies do the scoping and is
a lock-out for one whose policies are deliberately absent. The rule was applied
to both profiles because both had the same three words in their migrations, not
because both meant the same thing by them.

**A second regression from the same change, found 2026-08-25 while writing the
API surface tests.** The shared `services/api/koras_api/core/database.py`
imported `.tenant`, which the Control Plane does not have. It was dead code
there — nothing imported that module — until `verify_rls_enforcement` was added
to the lifespan and made it live. The control-plane API then failed to import at
all.

Two things kept it quiet. `ignore_missing_imports = true` means mypy treats an
unresolvable import as `Any` rather than an error, so a clean typecheck said
nothing. And no test imported the app, because the API was a workspace *member*
and not a root *dependency*, so `koras_api` was not installed in the environment
the root suite runs in — every existing test about the API read its source
instead of asking it.

Resolved by making the API a dev dependency of the generated root, and by
splitting `database.py` per profile: the product's carries the tenant-scoped
`get_db`, the Control Plane's a plain `get_session`, and the logic both need
moved into `koras_database`. A `_shared` template may not also exist in a
profile — `shared-template-parity.test.ts` enforces that, and caught the first
attempt at this split — so a package is where two profiles' shared logic
belongs.

**Condition 2 is now checked before the deploy, 2026-08-25.**
`local/scripts/check-rls-connection.sh` connects with the environment's own
`DATABASE_URL` and asks `pg_roles` whether that role is a superuser or holds
BYPASSRLS. The deploy workflow runs it in `migrate`, after the schema exists and
before anything is deployed against it — and `services` depends on `migrate`, so
a failure stops the release rather than producing one that will not boot.

`bootstrap:doctor` was the obvious home and is the wrong one: it is preflight,
running before the project exists, so it cannot know what role a database it has
not created will hand out. The question is only answerable once there is a
`DATABASE_URL`, which is why the check lives with the migration rather than with
the estate checks.

It reads the profile from `.koras/project.yaml` and skips on the Control Plane,
whose service role bypasses RLS by design — asserting the product's rule there
would refuse a correct deployment.

Verified against a real database in all four states: a superuser fails, a
non-superuser holding BYPASSRLS fails (the case a superuser check alone would
miss), an ordinary role passes, and a control-plane project handed a superuser
URL skips rather than failing.

**The role is now created rather than only demanded (2026-08-25).**
`local/scripts/create-app-role.sh` takes the privileged URL, creates
`koras_app` as `nosuperuser nobypassrls`, grants it only what the service needs
— including default privileges, so a table added by a later migration is not
invisible until somebody remembers to grant it — and prints the connection URL
to put in Doppler. It reads `rolsuper` and `rolbypassrls` back afterwards and
refuses to report success if either is true.

The credentials are split, and named so the privileged one is the one that looks
privileged:

| Doppler secret | Role | Used by |
|----------------|------|---------|
| `DATABASE_ADMIN_URL` | privileged | the deploy's `migrate` job only |
| `DATABASE_URL` | `koras_app` | every service |

A plain `DATABASE_URL` that happens to be a superuser is the trap this entry is
about, so the default name now carries the least privilege.

Verified against a real Postgres: the role is created, the connection check
passes for it and still fails for `postgres`, the role sees one tenant of two
with the context set, it can insert and read back, and a second run rotates the
credential and re-applies the grants rather than failing.

**Still not covered.** Nothing verifies this against a real Supabase project.
Supabase restricts what its `postgres` role may do, and it may refuse to create
a role at all — in which case the role must be made through its console and the
script re-run to apply the grants. The script says so on failure rather than
leaving it to be guessed, but the path is untested.

Also manual: running it. Four environments per project, once each, and deploys
fail until it is done.

---

## R-033 — the token checks were strictest on the token we issue ourselves

**Severity:** 9 (likelihood 3 × impact 3) · **Status:** Resolved 2026-08-25

Three verification paths ship in every generated project. Two of them —
the Next.js ZITADEL id_token path and the FastAPI bearer path — pinned the
audience and checked neither the issuer nor the algorithm. The third, the
session cookie this application signs itself, pinned both.

The looser checks were on the input arriving from outside and the stricter one
on the input the application generates.

The Python half was the worse of the two: `verify_token` already accepted an
`issuer` argument and defaulted it to `None`, so the check existed, was
opt-in, and nothing opted in. A reader of that function would see issuer
support and reasonably assume it was in use.

**Exploitability: low.** The key set is fetched from the configured instance,
so a token signed by another issuer fails the signature regardless. What was
missing is the check that does not depend on that remaining true — OIDC Core
§3.1.3.7 step 3 — and "the next check would have caught it" is the argument
that removes every check, one at a time.

**Resolution:** issuer and algorithm pinned on both ZITADEL paths, in both
profiles. `jwt-validation.test.ts` asserts all three paths pin signature,
audience where applicable, issuer, and algorithm. Each generated project also
gains a behavioural test signing with the correct key and a foreign `iss`,
which must be rejected — verified in the lab: 44 tests pass, up from 43.

**Assumption recorded:** the ZITADEL issuer equals the configured instance base
URL, which is how ZITADEL issues tokens. An instance fronted by a domain whose
`iss` differs would fail closed and loudly rather than opening.

---

## R-034 — the generated API has no rate limiting

**Severity:** 12 (likelihood 4 × impact 3) · **Status:** Resolved 2026-08-25

There is no rate limiting anywhere in the generated API: no per-caller quota,
no per-tenant quota, no request-size ceiling beyond the defaults of whatever
sits in front of it. OWASP API4:2023.

The token-verification path is the one that matters. It is reachable
unauthenticated by definition, and it is the most expensive thing the service
does — a JWKS lookup and an asymmetric signature check per request.

**Not mitigated by anything currently shipping.** Vercel and Fly both throttle
at the edge in ways that protect the platform rather than the tenant, and
neither knows what a tenant is.

**What closing it requires:** a limiter keyed on tenant *and* subject rather
than IP — callers arrive through a CDN, so the IP is the CDN's — applied ahead
of token verification so the expensive path is the protected one, with the
counter held in the environment's Upstash Redis rather than in process. The API
runs more than one machine, and an in-process counter is a per-machine counter
that multiplies the real limit by the machine count.

**Resolved.** `koras-ratelimit` ships to both profiles, counting in the
environment's own Upstash database.

Two tiers, because the description above was not quite coherent: a quota keyed
on tenant and subject cannot be applied *ahead of* token verification, since
both come out of the token. What protects the expensive path is a first tier
keyed on the client address, and the per-tenant quota is a second tier behind
`AuthDep` — which is what makes keying on `sub` safe, because an unverified
caller cannot reach it.

| Tier | Runs | Keyed on | Default |
|------|------|----------|---------|
| `limit_anonymous` | before verification | client address | 60/min |
| `limit_authenticated` | after verification | `organization_id` + `sub` | 600/min |

`X-Forwarded-For` is believed only when `trust_forwarded_for` is set, and it
defaults to false. Trusting it where no proxy rewrites it lets a caller vary one
header for a fresh quota per request — a limiter that limits nobody while
appearing to work.

Health is exempt. Limiting a load balancer probe takes the service out of
rotation, which is a self-inflicted outage.

**It fails open, and that is a real cost, stated rather than hidden.** An
unreachable Redis allows the request and sets `degraded` on the decision, so
while Redis is down there is no rate limiting. The alternative makes Redis a
hard dependency of every request — the same trade `koras_auth`'s JWKS cache
already refuses for the identity provider — and turns a limiter outage into a
total outage. `degraded` exists so this can be surfaced as a metric, because a
protection that silently stops protecting is worse than one that was never
there.

The window is fixed rather than sliding: one `INCR`, atomic, no script. The
boundary weakness is that a caller can spend a full quota at the end of one
window and again at the start of the next, so the true short-term ceiling is
twice the limit. Acceptable for abuse control; it would not be for billing.

11 tests ship with the package and run in every generated project; 18 more in
the generator assert the wiring.

---

## R-035 — `pnpm test` reported a cached pass over changed templates

**Found:** 2026-08-25, after CI failed twice on work that `pnpm test` had just
called green.

**Severity:** 16 (likelihood 4 × impact 4) · **Status:** Resolved 2026-08-25

`turbo.json` declared no `inputs` for `lint`, `typecheck` or `test`, so each
defaulted to `$TURBO_DEFAULT$` — the files inside that package's own directory.
The generator's test suite lives in `generators/create-koras-app/` and spends
most of its assertions on rendered output from `profiles/`, which is outside it.

So editing a template did not change the hash of `create-koras-app#test`, and
turbo replayed the previous result. `pnpm test` printed a full green summary,
including a test count, for a suite it had not run against the current
templates.

**What it cost.** The rate limiter went to the remote twice on the strength of
that green:

| Push | `pnpm test` said | CI found |
|------|------------------|----------|
| `4a5730b` | 731 passed | ruff import order; `starlette` undeclared; control-plane mypy |
| `39ad16a` | 731 passed | 2 failed — a stale assertion in a test edited minutes earlier |

The second is the clearest evidence. The assertion was rewritten and its
subject refactored in the same sitting, and the cached result still claimed 731
passing — a number that could only have come from before either change. The
totals even disagreed with CI's, 731 against 729, which was the visible thread.

**Why this is worse than a slow build.** A stale failure gets investigated. A
stale *pass* is indistinguishable from a real one, and it is trusted precisely
when it should not be: right after a change. Every "verified locally" claim
made against this command was worth less than it appeared, and the two CI
failures are the only reason anyone found out.

**Resolution:** `globalDependencies` in `turbo.json` now lists `profiles/**`,
`infrastructure/**`, `.claude/**`, `tsconfig.base.json` and
`eslint.config.mjs`. Any change to those invalidates every task's cache, which
is coarse and correct — a template edit can affect any package's rendered
output, and there is no cheaper way to say so.

Verified by editing a template and confirming the run misses cache rather than
replaying.

**The second half, fixed 2026-08-25.** `pnpm lint`, `pnpm typecheck` and
`pnpm test` ran only the JavaScript side. CI's Python job runs three more
things, and none had a local equivalent:

| CI step | Local before | Local now |
|---------|--------------|-----------|
| `uv run ruff check .` | nothing | `pnpm lint` |
| `uv run mypy .` | nothing | `pnpm typecheck` |
| `uv run pytest` | nothing | `pnpm test` |

A wider gap than this entry first described. It named ruff because ruff is what
failed; mypy and pytest were equally unrun locally and equally able to reach the
remote broken.

The root scripts now chain both languages, with `lint:py`, `typecheck:py` and
`test:py` available separately. Verified by reintroducing a ruff violation and
confirming `pnpm lint` exits 1 on it — the same class of defect that reached the
remote in `4a5730b` now fails before a commit.

`uv` is required for these to run, which is not a new dependency: the repository
is half Python, `uv.lock` is committed, and that half could not be verified at
all without it. A missing `uv` fails loudly rather than skipping, because a check
that silently does not run is the entire subject of this entry.

**Closing it in the starter exposed the same hole downstream, and 40 errors
behind it.** Every generated project had the identical gap — its `pnpm lint`
covered JavaScript only — and the factory never ran ruff on generated output
either. The generated projects' own `ci.yml` runs it, but that executes inside a
generated repository, never here, so a lint rule broken in a template was
invisible to the factory that shipped it.

A freshly generated product reported **40 ruff errors**:

| Count | Cause |
|-------|-------|
| 19 | `.claude/skills/` — vendored third-party code the project does not own. The starter excludes this tree; the template's `pyproject.toml` did not. |
| 17 | `python-packages/*/tests/` tripping S101. The template ignored `tests/**`, which matches only the top-level suite; the starter uses `**/tests/**`. |
| 2 | A middleware added this session with no type annotations. Mine. |
| 2 | Line length and an `f`-string with no placeholders. |

All fixed at the template, and `Lint (Python)` now runs in Generator
Integration, so generated output is linted by the factory rather than only by
whoever generates one.

The pattern is the same each time: a check that exists but never runs against
the thing it is supposed to check. The cached test result, the RLS suite never
executed, ruff never run on generated output — three instances in one session,
each invisible while everything reported green.

---

## R-036 — a live acceptance run could not be cleaned up

**Found:** 2026-08-25, while explaining what authorising a live apply would
involve. Nothing failed; the documents were read back and disagreed with the
code.

**Severity:** 12 (likelihood 3 × impact 4) · **Status:** Open

Phase 13 said a live apply was a manual runbook step and that "teardown is what
makes it repeatable". Teardown does not make anything repeatable, because it
does not delete.

`tests/e2e/helpers/teardown.ts` — since moved to
`tooling/koras-cli/src/teardown/guards.ts` — holds four guards, sixteen tests,
and no provider call. Every `Deleter` is injected and no implementation exists, so the
suite proves the guards refuse the right names and proves nothing about
deletion. It also models three resource kinds — GitHub repositories, Doppler
projects, Supabase projects — where a provision writes to seven. Upstash,
ZITADEL, Vercel and Fly are absent entirely.

`terraform destroy` is not the fallback. `prevent_destroy = true` is set on the
GitHub repository, Supabase projects, Upstash databases, Vercel projects and Fly
apps, and the generator exposes no destroy path at all. Destroy fails on each of
those until somebody edits the modules — correct for a real estate, and exactly
what makes an acceptance estate unrepeatable.

**What that means in practice.** One product-profile apply creates roughly
35–40 resources across seven providers, including four Supabase projects and
four Upstash databases that bill. Cleaning that up today means seven provider
consoles and a person who remembers what was created. Anything missed keeps
costing money, and the Upstash guard exists precisely because those databases
hold queue state.

**Why it survived.** The guards were built first, deliberately and correctly:
they are what any real deleter must pass through. The gap was then described in
the roadmap as "the half that can be built and tested safely", which reads as
*this half is done* rather than *this half is the guards*. The tests being green
reinforced it — sixteen passing tests about deletion, none of which delete.

Same shape as R-035 and the RLS suite before it: a check that exists, is tested,
and never touches the thing it is supposed to act on.

**Mostly built, 2026-08-25.** `koras teardown <project> <outputs.json>` exists.
The guards moved from `tests/e2e/helpers/` into `tooling/koras-cli/src/teardown/`
— they had looked like test scaffolding and are the safety mechanism of a
destructive command — and six of the seven providers now have delete calls
behind them.

The inventory is built from Terraform's own outputs rather than by listing each
provider and filtering by name. State is the record of what was created; a
listing is a guess that can both miss and over-match.

Verified through the command itself, not only through unit tests. Given a real
project's outputs with `KORAS_E2E_TEARDOWN=1` set, all eight resources are
refused by name. Given an acceptance project's outputs with the flag unset, it
reports a dry run and issues nothing.

**What is still open:**

1. ~~**ZITADEL has no deleter.** Its API needs a service-account JWT exchange
   rather than a bearer token.~~ **Wrong, and built 2026-08-27.**

   There is no JWT exchange. `local/zitadel/provision.py` has always talked to
   the same management API with `Authorization: Bearer <personal access token>`,
   and the token in question — `ZITADEL_SERVICE_TOKEN` — is one the estate
   already holds. The stated blocker was never tested because it was not a
   claim about behaviour; it was a comment explaining an absence, and the one
   sentence in a file of tested code that nothing could contradict.

   It surfaced sideways. A reader asked why a Doppler secret was missing, the
   audit of that config turned up `ZITADEL_SERVICE_TOKEN`, and reading what it
   was for is what showed the comment to be false. Nobody was looking at
   teardown.

   The real difficulty was elsewhere, and unstated: **which organization to act
   in**. ZITADEL projects are org-scoped and the management API acts in the org
   of whoever holds the token. This estate has two active organizations, so a
   delete aimed at the wrong one returns 404 — indistinguishable from a project
   that is already gone, which teardown counts as success. The failure mode was
   not "cannot delete"; it was "reports having deleted".

   So the org travels with the resource: `zitadel_resolved_org_ids` is a new
   root output, paired by environment with `zitadel_project_ids`, and the
   deleter sends it as `x-zitadel-orgid`. The instance URL travels the same way
   — ZITADEL is self-hosted per environment, so there is no single API to
   default to. A project whose org or instance is unknown is refused loudly
   rather than deleted hopefully or dropped from the inventory.

   `UNIMPLEMENTED_KINDS` is now empty and kept: it is the mechanism by which a
   future gap is visible rather than silent.
2. **`prevent_destroy` is untouched.** It is irrelevant to the API-based path
   above, which never invokes Terraform — but `terraform destroy` still fails on
   five resource types, so anyone reaching for it will be stopped.
3. **Nothing has been run against a real provider.** Every test injects a
   `fetch` double. A green suite means the requests are shaped as the API
   documents; it does not mean any provider accepts them. This is the last
   thing standing between R-036 and closed, and it is the one item on this list
   that no amount of test-writing can retire.

4. **A general form of R-040 is now closed.** `parseTerraformOutputs` reads
   each value by name and returns empty when it is absent — correct, because a
   provision that made no Vercel projects should not throw, and indistinguishable
   from a typo. That tolerance is what made `redis_database_ids` return `{}`
   forever. `terraform-output-names.test.ts` now compares the names the parser
   reads against the outputs both profile roots emit, so a name nobody exports
   fails instead of parsing as nothing. Mutation-checked: renaming one output by
   a single character fails three assertions.
4. ~~The GitHub token cannot delete repositories.~~ **Wrong, corrected
   2026-08-25.** `delete_repo` is the *classic* token scope name; the estate
   uses a fine-grained token, where repository deletion falls under
   **Repository → Administration: Read and write** — which it already holds,
   for branch protection. Checked against the token's settings. This was
   recorded as a blocker for several hours and was never one.

So a live apply is closer to reversible than it was, and is not yet reversible.
Point 3 is what stands between the two: nothing here has met a real API.

**A confirmation was added on top of the guards (2026-08-25).** With deletion
enabled and a plan that is not empty, the command names the project and the
resource counts and requires the operator to type the project name back. `yes`
is refused, an empty answer is refused, and a session with no terminal is
refused rather than reading EOF as agreement.

`confirmApply` in the generator asks for `yes` before *creating* infrastructure.
This asks for more because the mistakes differ: applying to the wrong project
leaves resources that can be deleted, and deleting the wrong project leaves
nothing. `yes` is a reflex by the third time anyone sees it; a name has to be
read off the screen and matched against what the prompt says it is about.

There is deliberately no `--yes` or `--force`. A flag that skips confirmation is
the first thing a script reaches for, and a script is what should never be able
to run this.

---

## R-037 — the typecheck was configured to ignore the error it needed to report

**Found:** 2026-08-25, after R-032's second regression showed a green `mypy` on
an API that could not import.

**Severity:** 12 (likelihood 4 × impact 3) · **Status:** Resolved 2026-08-25

Both profile templates set `ignore_missing_imports = true` globally. That does
not only silence third-party packages without stubs: it makes mypy treat **any**
unresolvable import as `Any`, including a first-party module that does not
exist. `from .tenant import TenantDep` against a module the Control Plane does
not have typechecked clean and failed at runtime with `ModuleNotFoundError`.

Demonstrated both ways rather than argued. With the global setting, an import of
a deliberately non-existent module reports `Success: no issues found in 33
source files`. With it narrowed, the same import reports
`Cannot find implementation or library stub for module named ...`.

**What actually needed it: one package.** Turning the setting off and reading
what complained produced exactly one name, `jose`, which ships no type
information and has no stubs package. A global switch had been disarming the
strongest static check these projects have, for a single dependency.

**Resolution:** `ignore_missing_imports = false` globally, with a
`[[tool.mypy.overrides]]` block naming `jose.*` and `apscheduler.*`.
`apscheduler` is listed in both profiles even though the product generates no
scheduler by default — it is an optional service there, so `--with scheduler`
would otherwise fail a check that passed before the flag was used.

### A second defect, found because narrowing made the run honest

`--with scheduler` on the **product** profile produced a project that failed its
own typecheck, and had for as long as the flag existed.

APScheduler's `scheduled_job` carries no type information, so under `strict` it
makes every job body untyped — switching off checking inside the job bodies,
which is the one place a scheduler's mistakes are expensive. The Control Plane's
copy carried `# type: ignore[untyped-decorator]` at each use and a comment
explaining why. The product's copy did not.

A fix landed in one profile and not the other, which is the drift class this
repository keeps producing. It survived because the product's scheduler is
**optional**: default generation omits it, so no CI run and no local check ever
typechecked it. `shared-template-parity` could not catch it either — it forbids
byte-identical copies, and these two differed, which is precisely how the
divergence hid.

Resolved by bringing the product's copy in line, at which point the two became
identical and the parity test demanded they be single-sourced. `main.py` now
lives in `_shared`; the rest of the scheduler already did.

**Left standing:** nothing generates with optional components and checks the
result. `--with marketing,ai_gateway,scheduler` and the `--without` variants are
untested paths through the generator, and this defect sat in one of them. Worth
a matrix entry in Generator Integration rather than a comment here.

---

## R-038 — the drift check reported drift for every optional component

**Found:** 2026-08-25, by the CI entry added to close SYNC_BACKLOG D5. It failed
on its first run.

**Severity:** 9 (likelihood 3 × impact 3) · **Status:** Resolved 2026-08-25

`--check-drift` re-derived its component selections from the profile's defaults
rather than from the project in front of it. A project generated with
`--with scheduler` was therefore compared against a rendering that has no
scheduler, and every one of its scheduler files was reported as drift — by the
command whose entire purpose is to say what has drifted.

The same in reverse for `--without`: a project generated without the worker was
told the worker was missing.

**Not a CI problem.** The matrix entry is what surfaced it, but the defect is in
the CLI and reaches every operator who used an optional component. The report
was wrong in the field, and wrong in a way that trains people to disbelieve it —
which is worse than not having it, because the next report is real.

**Resolution:** a read-only command now reads the component set from the
project's own `.koras/project.yaml`, which records it precisely so this is
knowable without anyone remembering flags passed a year earlier. Explicit
`--with` / `--without` still win, because `--check-drift --with worker` on a
project without one is a question about what it *would* look like, and answering
it from the recorded set would ignore the question.

A manifest predating the `components` field records nothing, and the previous
behaviour is left in place for those projects.

**Why nothing caught it.** `components` was added to the manifest for exactly
this purpose and then only ever read by `compareSelections`, which checks the
manifest against `terraform.tfvars`. The field that would have answered the
question was present, populated, and consulted for a different one.

`--check-drift` is also the last step of Generator Integration, so it had been
running on every push — against default components only, where the defect does
not appear.

---

## R-039 — the ZITADEL module could only extend an estate it had already built

**Found:** 2026-08-25, by a `--provision --dry-run` on a new project. The plan
failed; nothing was created.

**Severity:** 16 (likelihood 4 × impact 4) · **Status:** Resolved 2026-08-25

```
Error: Missing required argument
  with module.bootstrap.module.zitadel_stg.zitadel_project_role.roles["organization_admin"]
  93:   org_id = zitadel_project.this.org_id
  The argument "org_id" is required, but no definition was found.
```

`org_id` on `zitadel_project` is **Optional and not Computed** — confirmed
against the provider schema, not inferred. Leaving it unset does not mean the
provider fills it in; it means the attribute plans as `null`. So
`zitadel_project.this.org_id` is null for any project that is not already in
state, and `zitadel_project_role` requires it.

The module's own comment described the optionality correctly and drew the wrong
conclusion from it — that the provider "resolves the organization and writes the
result into state" was true, and irrelevant at plan time for a resource that
does not exist yet.

**Every existing environment kept working**, because its state already held the
value the provider had written on first apply. Only a *new* environment failed
— which is the one thing `create-koras-app` exists to produce. A module that
could extend an estate it had already built and could not start one.

**Why nothing caught it.** Every acceptance test in this repository supplies
Terraform's output as JSON rather than running Terraform, deliberately: the
alternative is an apply across seven providers. That makes everything
downstream of the outputs testable and leaves the configuration itself checked
only by `terraform validate`, which passes — the reference is syntactically
perfect and semantically null. `terraform plan` against a real instance is the
first thing that can see it, and this was the first plan against one.

**Resolution:** the organization is discovered before anything is created,
through `data "zitadel_orgs"` filtered to active, and every resource takes
`local.org_id`. One active organization per instance is the estate's
arrangement; `var.org_id` overrides it where that does not hold, and a
`precondition` on the project says how many were found and what to set rather
than failing on a null further down.

`ignore_changes = [org_id]` is kept. The provider still writes the resolved
organization back, a project cannot move organizations without being recreated,
and a diff there could only propose destroying an environment that is serving
traffic.

**Verified against the live estate.** The next plan resolved three of four
instances outright:

| Instance | org_id |
|----------|--------|
| prod | `386574892088285534` |
| stg | `386574498930987922` |
| test | `386574248430375826` |

`Plan: 99 to add, 0 to change, 0 to destroy`, with `zitadel_project_role`
finally receiving a concrete organization instead of null.

**dev holds two active organizations**, so the precondition fired rather than
guessing — the designed outcome, and the message was not good enough. Two bare
ids say nothing about which organization is the KORAS one, so answering it meant
a trip to the console. A second lookup now fetches each organization's name and
the error reads `id (name)`.

An instance that must be told takes `ZITADEL_<ENV>_ORG_ID` from Doppler, through
`zitadel_instances[env].org_id` and a `zitadel_org_ids` map into the bootstrap
module. Ids only: the providers are configured at the root, so passing the whole
instance object would hand that module service-account JWTs it has no use for.
An absent id stays absent rather than arriving as null, because the Terraform
type is `optional(string)` and the two differ there.

**A change that spans a module and a rendered file lands half-applied.**
`--refresh-modules` refreshes shared assets and nothing else, which is correct
and is not obvious. The ZITADEL fix touched `modules/zitadel` *and*
`infrastructure/terraform/main.tf`, which passes the new variable in. Refreshing
brought the module forward and left the caller on the old signature, so the plan
kept failing with the original error and looked like the fix had not worked.

Two rounds of re-running went by before anyone read the files. The diagnosis
took one command:

| Link | State after `--refresh-modules` |
|------|-------------------------------|
| `modules/zitadel/main.tf` | current |
| `modules/project-bootstrap/variables.tf` | current |
| `infrastructure/terraform/main.tf` | **stale** — did not pass `zitadel_org_ids` |
| `infrastructure/terraform/variables.tf` | **stale** — instance type had no `org_id` |

`--refresh <path>` brings a rendered file forward, and `--check-drift --all`
lists what is behind. Neither was reached for, because nothing said the flag had
limits. `formatRefreshResult` now prints them on every run.

**Still unverified:** the apply itself. A plan that succeeds is not an apply that
succeeds, and dev has not planned cleanly yet.

---

## R-040 — teardown reported a complete run and left a whole provider alive

**Found:** 2026-08-26, on the first real teardown. It printed
`Teardown — 26 deletable, 0 retained` and every line said `deleted`.

**Severity:** 16 (likelihood 4 × impact 4) · **Status:** Resolved 2026-08-26

Four Upstash Redis databases were created by the apply and appeared nowhere in
the inventory. They were still running, and billing, after a teardown that
reported success.

`inventoryFromOutputs` read `outputs.redisDatabaseIds`. No such output existed:
the Upstash module exported `redis_urls` (sensitive, and dropped by the parser)
and `redis_endpoints` (a hostname, which the delete API cannot use), and never
an id. The parser had no such field either. So the expression evaluated to
`undefined`, the `?? {}` fallback turned that into an empty map, and Upstash
silently contributed nothing.

**Every layer was individually reasonable.** The module exported what the
bootstrap script needed. The parser mapped the outputs that existed. The
inventory read the field it expected. Nothing connected them, and the type
that should have was `redisDatabaseIds?: Record<string, string>` — optional,
so a caller omitting it was legal, and every caller omitted it.

**What made it invisible.** A missing provider has no symptom. A failed
deletion prints `failed`; a provider that never enters the inventory prints
nothing at all, and the summary counts only what it found. `0 retained` reads
as "nothing was left behind" and means "nothing I looked at was left behind".

ZITADEL was handled the opposite way on purpose — it has no deleter and is
listed as skipped with the reason — and that is exactly why it did *not* go
missing. The same care was not taken for a provider nobody remembered was
there.

**Resolution:**

- `redis_database_ids` is exported by the Upstash module, re-exported by
  `project-bootstrap`, and surfaced at the root. Ids, not endpoints: the delete
  API takes an id, and an id addresses a database without opening one, so it is
  not sensitive and survives the parser.
- `parseTerraformOutputs` reads it into `redisDatabaseIds`.
- The inventory's field is **required**, not optional. A missing output is now
  a type error at the boundary rather than an absence discovered from a bill.
  Making it required immediately failed the build until the parser was updated,
  which is the check that was missing.
- A test asserts the inventory contains all seven kinds, rather than the ones
  that happen to work.

**Cleanup of the run that found it was manual.** Four databases named
`koras-e2e-test-*` had to be removed from the Upstash console, because the
teardown that should have removed them had already reported success.

---

## R-041 — a teardown instruction told the operator to write credentials to disk, and they were committed

**Found:** 2026-08-26, by `gitleaks` failing the Security workflow — after the
commit had been pushed to a public repository.

**Severity:** 20 (likelihood 4 × impact 5) · **Status:** Resolved 2026-08-26

`koras teardown` took a path to a file produced by `terraform output -json`.
That command **includes the values of outputs marked sensitive**, so the file it
writes is a credential store: four Upstash URLs each embedding its password, and
four ZITADEL client secrets. The teardown instructions said to write it into the
repository working directory.

It was then committed by a `git add -A`, and pushed. Public.

**Two failures, and the second is the one worth keeping.**

The immediate one is `git add -A` in a directory known to contain a credential
file. That is a discipline failure and the fix is discipline.

The design failure is worse: **the command required a credential-bearing
artifact to exist at all.** Teardown needs ids — Fly app names, Supabase refs,
Upstash database ids — every one of them non-secret. It never needed the
passwords. The file carried them because `terraform output -json` emits
everything and nobody filtered it. An interface that makes the caller
materialise secrets it does not use will eventually have one of them
mishandled, and the mishandling is a symptom.

**What worked.** `gitleaks` caught it, on history, and failed the build. That
job had never run before 2026-08-25 (R-030) and had been green ever since, so
this is its first real finding. Scanning history rather than the working tree is
what made it catch a secret already deleted from the tree.

**Resolution:**

- `koras teardown <project> -` reads the outputs from stdin, so the documented
  form is `terraform output -json | pnpm koras teardown <project> -` and nothing
  reaches disk. A file path still works, and the help says plainly what it costs.
- `.gitignore` covers `*-outputs.json` and `terraform-outputs*.json`.
- `.gitleaks.toml` allowlists the two specific commits that carry the file, by
  full SHA, with the reason. Not the path: a future leak in a file of that name
  is a new finding and must fail.

**Remediation.** History was not rewritten. Rewriting a pushed public branch
does not un-distribute what has already been fetched, and pretending otherwise
is worse than recording it. The credentials were destroyed by deleting the
resources they belonged to, which is the only remedy that works after
disclosure.


---

## R-042 — prose is the only part of this repository that can be wrong quietly

**Severity 12 (likelihood 4 × impact 3). Partly closed 2026-08-27.**

Three defects inside one session came from documentation and comments rather
than from code, and none of them could have been caught by the test suite:

| Claim | Where | Reality |
|-------|-------|---------|
| ZITADEL teardown "needs a service-account JWT exchange rather than a bearer token" | `providers/index.ts` | Never true. A bearer token has always worked, and the estate already held one |
| `DATABASE_ADMIN_URL` "is not an application setting, so it is absent from `secrets.manifest`" | `PROVISIONING_RUNBOOK.md` | A decision, and the wrong one. The preflight could not ask for a secret the deploy required |
| `ZITADEL_SERVICE_TOKEN` is an orphan | a Doppler audit | The secret was real; the *factory's declaration* of it was missing |

The common shape is not carelessness. Each was a statement about something that
does **not** exist — an unbuilt deleter, an omitted entry, an undeclared
setting — and an absence has no behaviour to assert. Every other claim in this
repository is executable and has a test standing behind it; these three were the
kind that no green suite could ever have contradicted, which is exactly why they
survived being read many times.

**What is now checked.** `tests/docs/file-references.test.ts` verifies that every
path a document names exists. That covers claims about *where*, which is the
commonest kind of documentation rot — files move and the prose does not move
with them — and it found two stale references the moment it was written.

Two escape hatches exist and both are self-checking, because an exemption is a
claim as well:

- `ABSENT_ON_PURPOSE` — paths named in order to say they do not exist. Each is
  asserted *absent*, so a document claiming a file was never created fails when
  somebody creates it.
- `MOVED` — old paths kept inside dated accounts, where editing the path would
  falsify the record. The old path must be gone *and* the replacement must
  exist.

Mutation-checked in both directions: an invented path in a document fails, and
an exemption naming a file that does exist fails.

**What is still open, and cannot be closed this way.** A false claim about
*where* is mechanical. A false claim about *why* — the JWT sentence, the
manifest reasoning — is not. The only defence there is that an explanation of
why something is absent should be treated as the least trustworthy sentence in
any file, because it is the one thing nothing can verify. Prefer building the
thing to explaining why it is missing.
