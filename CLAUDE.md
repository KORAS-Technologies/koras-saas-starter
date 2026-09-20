# KORAS SaaS Starter — AI Agent Context

## What this repository is

`koras-saas-starter` is the KORAS application factory. It generates two categories
of repository through a declarative CLI:

```
pnpm create-koras-app <project> --profile <profile>
```

| Profile         | What it generates                                    |
|-----------------|------------------------------------------------------|
| `product`       | A KORAS SaaS product (Docoris, Dianova, LegalApp, …) |
| `control-plane` | KORAS Control Plane — the provisioning authority     |

## Key documents

All planning and reference documents live in `docs/`, matching
`koras-control-plane`. Only `README.md` and this file sit at the root.

| Document                         | Purpose                                          |
|----------------------------------|--------------------------------------------------|
| `docs/ARCHITECTURE.md`           | System overview and technology choices           |
| `docs/PROFILE_ARCHITECTURE.md`   | Capability matrix for both profiles              |
| `docs/PRODUCT_GENERATOR_PLAN.md` | Generator CLI design                             |
| `docs/INFRASTRUCTURE_PLAN.md`    | Terraform module strategy                        |
| `docs/ENVIRONMENT_STRATEGY.md`   | Branch ↔ environment mapping (immutable)         |
| `docs/DEPENDENCY_MAP.md`         | Package and service dependency graph             |
| `docs/IMPLEMENTATION_ROADMAP.md` | Phase-by-phase build plan                        |
| `docs/BOOTSTRAP_DOCTOR.md`       | `pnpm koras bootstrap:doctor` — preflight checks |
| `docs/PROVISIONING_RUNBOOK.md`   | Commands, estate prerequisites, failure recovery, teardown |
| `docs/RISK_REGISTER.md`          | Identified risks and mitigations                 |
| `docs/OWASP_CHECKLIST.md`        | OWASP API Top 10 review of the generated API     |
| `docs/SYNC_BACKLOG.md`           | Gaps between the factory, the two profiles and the generated repositories |
| `docs/CLAUDE_CODE.md`            | Claude Code skills, profiles and inheritance      |
| `docs/REGISTRATION_LIFECYCLE.md` | When a product registers, and what each pass carries |
| `docs/FOLLOW_UPS.md`             | Work identified and deliberately left undone, with the reason |
| `docs/NEW_PRODUCT_WALKTHROUGH.md` | A worked example: new product to visible in the console |
| `docs/PRODUCT_FRONTEND.md`       | The generated product's frontend: tokens, branding, pages |
| `docs/PRODUCT_APP_SHELL.md`      | The authenticated product shell: navigation registry, access model, product settings |
| `docs/PRODUCT_SHELL_AUDIT.md`    | What the signed-in surface was before that shell, and the gaps it closes |
| `docs/BILLING_DESIGN.md`         | Card at signup, charge at trial end: Stripe Managed Payments behind an adapter, phases and test evidence |
| `docs/PRODUCT_SIGN_IN.md`        | The product's own sign-in page: how a customer signs in without seeing ZITADEL, and what is not yet checked live |
| `docs/AI_FOUNDATION_ASSESSMENT.md` | What the repository had before the AI foundation, what it lacked, and where the request conflicted with decisions already made |
| `docs/AI_FOUNDATION_PLAN.md`     | The AI foundation in phases: files, decisions, tests |
| `docs/AI_ARCHITECTURE.md`        | The AI foundation as built: one runtime in the API, aliases in product code, the gateway as the only provider |
| `docs/AI_DEVELOPER_GUIDE.md`     | How a generated product enables AI and adds agents, tools, prompts and knowledge |
| `docs/AI_SECURITY.md`            | The assistant as an untrusted subsystem: tenant, authorization, tools, injection, secrets, audit |
| `docs/AI_CONTROL_PLANE_CONTRACT.md` | What a product reads from the platform today, and what the platform would need to offer |
| `docs/adr/0001-koras-shared-ai-foundation.md` | The decision record for the shared AI foundation |
| `docs/REPORTING_ARCHITECTURE.md` | Reporting and analytics: one registry, three levels, every report server-authorized |
| `docs/adr/0002-koras-reporting-framework.md` | The decision record for the reporting framework |
| `docs/adr/0003-koras-storage-audit-governance.md` | The decision record for storage and audit governance |
| `docs/STORAGE_ARCHITECTURE.md`    | Storage as built: the provider seam, the key, the index, scanning, reconciliation |
| `docs/AUDIT_ARCHITECTURE.md`      | Audit as built: the envelope, the action registry, the four classes, retention |
| `docs/RETENTION_POLICY.md`        | How long things are kept, the precedence, and which half is still design |
| `docs/BACKUP_AND_RESTORE.md`      | Backup and restore: the design, and why none of it is built |
| `docs/adr/0004-storage-provider-abstraction.md` | Why the provider seam is narrow, and what it refuses |
| `docs/adr/0005-storage-object-hierarchy.md` | What is in an object key, and the five things deliberately left out |
| `docs/adr/0006-backup-strategy.md` | Backup: what is settled, and the three questions that block building it |
| `docs/features/README.md`         | The feature catalogue, and how it relates to the flat documents |
| `docs/features/STATUS.md`         | Every SAG story, its class and its status, and the settings framework's eleven phases |
| `docs/SETTINGS_ARCHITECTURE.md`  | Settings as built: three levels, a snapshot per organisation, a catalogue declared in code |
| `docs/SETTINGS_DEVELOPER_GUIDE.md` | How to add a setting, how to read one, and the four things that will bite |
| `docs/adr/0007-koras-settings-framework.md` | The decision record for the settings framework, amended twice |
| `docs/platform/master-platform-plan.md` | One audit and one plan for three feature categories: notifications, data import, Stripe provisioning |
| `docs/platform/master-capability-matrix.md` | Every platform capability those three touch: exists, partial or absent, and where |
| `docs/platform/gap-defect-register.md` | The 45 findings that audit produced, by category, with IDs |
| `docs/platform/execution/` | One manifest per category, each executable without repeating the audit |
| `docs/features/data-import/` | Data import as built: Phase 1 stops at the dry run, and the three plan items it deliberately left |
| `docs/adr/0009-import-runs-are-not-a-third-export.md` | Why an import run has its own table rather than a third copy of the export pattern |
| `docs/ENGINEERING_FRAMEWORK.md` | The product's multi-agent framework: one vocabulary, risk by boundary, gate reuse, bounded loops |
| `docs/adr/0010-koras-engineering-framework-v2-1.md` | The decision record for V2.1 of that framework |
| `docs/adr/0008-koras-platform-job-and-notification-contracts.md` | Why the job contract is built first, and why notification gets a dispatch point rather than a bus |

## Repository layout (target state)

```
apps/              Next.js applications
services/          FastAPI / Python backend services
packages/          Shared TypeScript packages
python-packages/   Shared Python packages
profiles/          Generator profile manifests and templates
  _shared/         Template layer both profiles draw from; not a profile
  product/         SaaS product profile
  control-plane/   Platform authority profile
generators/        create-koras-app CLI
supabase/          Database migrations, policies, functions
local/             Docker Compose local development stack
infrastructure/    Terraform modules
deploy/            Deployment scripts
scripts/           Utility scripts
tooling/           Build tooling
docs/              Documentation
tests/             Integration and e2e tests
```

## Technology stack

- **Frontend:** Next.js 15, TypeScript 5, Tailwind CSS, shadcn/ui, Turborepo, pnpm
- **Backend:** FastAPI, Python 3.12+, SQLAlchemy 2, ARQ, APScheduler
- **Database:** Supabase (PostgreSQL) with RLS
- **Queue:** Upstash Redis — one database per environment, never shared
- **Auth:** ZITADEL (OIDC — customers never see ZITADEL UI)
- **Secrets:** Doppler (sole secret authority — nothing committed)
- **IaC:** Terraform
- **Hosting:** Vercel (frontend), Fly.io (backend), Cloudflare (DNS/CDN)

## Environment model

| Environment | Branch    | Notes                        |
|-------------|-----------|------------------------------|
| `dev`       | `develop` | Fast feedback; may be broken |
| `test`      | `test`    | Automated test suites        |
| `stg`       | `staging` | Pre-production sign-off      |
| `prod`      | `main`    | Live traffic                 |

This mapping is immutable (ADR required to change).

## Profile templates

A generated project is rendered from two template layers:

```
profiles/_shared/template/     walked first
profiles/<profile>/template/   walked second, and wins on a shared path
```

Both are rendered through Handlebars and then filtered by the profile's
`template_map`, so a shared file may be a `.hbs` and may live inside a
capability-gated subtree. A profile that ships its own copy of a shared path
overrides it — the file existing twice is the signal that the divergence was
deliberate.

`shared_assets` in a profile manifest is a different mechanism and stays for a
different job: it copies a directory **verbatim and unconditionally** from the
starter, which is right for the Terraform modules and for `.claude/`, and wrong
for anything that needs rendering or capability gating.

`profiles/_shared/` is not a profile. `VALID_PROFILES` is an explicit list, so
nothing enumerates it as one.

No file exists twice. `shared-template-parity.test.ts` asserts that
structurally -- no path may exist in both profile templates with byte-identical
content -- rather than by listing paths, so a file duplicated tomorrow is caught
without anyone remembering to add it. 142 files are single-sourced in `_shared/`;
the 48 paths that exist in both profiles do so with genuinely different content,
which is deliberate divergence rather than duplication.

The comparison normalises trailing whitespace as well as line endings. It did
not, and five Python package markers were duplicated across both profiles for
months — empty in one, a single newline in the other. Two bytes is not zero
bytes, so the test passed every time it ran.

## Generator rules

- `--profile` is always required in non-interactive mode
- Profile is never inferred from project name
- `--output-dir` is effectively required — generating into the starter is refused
- Terraform never auto-applies — explicit human approval required
- Generator never silently overwrites or destroys existing resources
- Secret values are never exposed in logs, output, or registration payloads
- `--profile control-plane` never requires a pre-existing Control Plane
- Credentials are pulled from Doppler by the CLI itself; no `doppler run`
  wrapper is typed, and an outer one is never nested
- Generated projects claim no fixed host port — `local/scripts/ports.sh`
  resolves them per machine into `local/.env`

## Claude Code configuration

`.claude/` at the repository root is the **single source of truth** for the
Claude Code configuration of every KORAS repository — this one and every project
generated from it.

```
.claude/
  CLAUDE.md                     Shared Koras engineering instructions
  commands/                     /feature, /review, /test, /ui-review
  agents/                       architect, frontend, reviewer, tester
  skills/koras-*/               The twelve common Koras skills
  skills/frontend-design/          skills/webapp-testing/          } Vendored external skills, pinned in
  skills/react-best-practices/    } .claude/external-skills.yaml and locked in
  skills/web-design-guidelines/  /  .claude/external-skills.lock.json
  scripts/sync-external-skills.mjs
  external-skills.yaml
  external-skills.lock.json
```

Both profile manifests declare `.claude` as a `shared_asset`, so
`create-koras-app` copies this tree verbatim into every generated project. On
top of it each profile template carries exactly one overlay skill:

| Profile | Overlay, at `profiles/<profile>/template/.claude/skills/` |
|---------|----------------------------------------------------------|
| `product` | `koras-profile-product/` |
| `control-plane` | `koras-profile-control-plane/` |

Common configuration plus one profile overlay — never two duplicate trees. A
generated project identifies its own profile from `.koras/project.yaml`.

**The product profile carries one thing more.** The multi-agent engineering
framework — 40 agent definitions, the orchestration contract, the domain
framework and the feature documentation templates — is product-only, at
`profiles/product/template/.claude/`. It cannot be a `shared_asset`: that
mechanism copies unconditionally into both profiles, and a Control Plane
repository carrying a customer-product orchestration contract looks entirely
normal until an agent follows it. `generators/create-koras-app/tests/orchestration.test.ts`
asserts both directions, plus the things that otherwise fail silently — that the
registry count matches the files on disk, that every agent id named in the
workflow, activation rules and gates resolves, that every documented file has a
template, and that the 40 definitions are not 40 copies of one file.

This starter is the factory, not a generated project: it carries the common
configuration and no overlay. Profile rules are *authored* here, not applied
here.

See `docs/CLAUDE_CODE.md` for how to add a skill, add a profile, upgrade the
external skills, and bring an existing project back into alignment.

## Current phase

**Phases 0–12 complete.** Phases 10, 11 and 12 met their exit criteria on
2026-08-25. Phase 13 is complete except its live-infrastructure variant.

**Open:**

| Phase | State | Note |
|-------|-------|------|
| 13 — End-to-End Acceptance Tests | Live variant run, one gap found | A product estate of 82 resources was provisioned and torn down on 2026-08-27. Seven providers deleted cleanly; **Cloudflare was not in the inventory at all**, so eight DNS records survived a run reporting nothing retained. Now the eighth provider — R-036 reopened for a second live run |

**Open risks:** R-036 (a second live teardown, now that Cloudflare is in the
inventory) and R-042 (documentation and comments are the one part of the
repository that can be wrong without anything going red). R-042 shrank on
2026-09-15: hedged claims — "not yet", "currently", "for now" — are now checked
by `tests/docs/hedged-claims.test.ts`, which requires a date in the hedge's own
paragraph, heading or table row. That is the fourth mechanical class, after
paths, lists and identifiers. What is left of R-042 is claims about *why*, which
nothing can reach.

**R-031 closed on 2026-09-15.** `vitest` is on 4.x with `vite` and `esbuild`
patched, `pnpm audit` finds nothing, and the suite passes. The upgrade was
blocked for three weeks by workers blocked on synchronous filesystem work; what
actually fixed it was making the generator's `writeFiles` path asynchronous and
giving the suites that spawn real processes a budget that matches them.

R-030 was reopened for products on 2026-08-30 and **re-closed the same evening**,
when Actions billing was resolved; this line said otherwise for two days, which
is R-042 landing on the file every session reads first. `koras-e2e-shop` runs CI
and deploys to dev on every push. Products stay private by design, so an Actions
billing failure would re-block every run and reopen it again.

`output/sample-product` no longer exists. It was deleted on 2026-08-30 —
41 resources across eight providers — because the credentials a committed plan
file published in it could not be un-published, and destroying what they reach
is the only remedy that works after disclosure. FOLLOW_UPS F1 records what was
removed. The product repository today is `koras-e2e-shop`, provisioned and
pushed the same day (F15). **Nothing syncs it** — a generated project has no
upstream and the factory pushes to nothing, so it is kept level by a hand-
carried `chore: sync … from the starter` commit per change, and `--check-drift`
sees only files it never received, not content drift in files it has. Template
breakage is still caught independently by Generator Integration building a
product from the templates.
R-031 stands accepted with mitigation.

**The AI foundation shipped on 2026-09-13** as a product capability, `ai`, off
by default and requiring the `ai_gateway` service: a Python runtime in the API,
aliases in product code, the gateway as the only provider, tools with
deterministic permission checks and human approval for anything that is not a
read, usage metered per call, and an assistant page and drawer in the shell.
`docs/AI_ARCHITECTURE.md` is the description; F24 in `FOLLOW_UPS.md` is what it
leaves out, the first of which is that no model has yet been called through a
deployed gateway.

**The reporting framework shipped on 2026-09-14** as a product capability,
`reporting`, on by default: the `koras-reporting` package in the shared layer
(definitions, registries, typed filters, the visibility rule, CSV), six
standard tenant reports over the tables the starter creates, a general
`audit_events` table, an `analytics` module that replaced the `reports`
placeholder, five `reporting.*` entitlements in the Control Plane's catalogue,
a platform Analytics section in the Control Plane built on the same package,
and seven shop reports in `koras-e2e-shop` registered through the extension
point over a shop domain that repository now has. `docs/REPORTING_ARCHITECTURE.md`
is the description; F25 in `FOLLOW_UPS.md` is what it leaves out.

**Storage and audit governance began on 2026-09-15 and is part built.** Read
`docs/adr/0003-koras-storage-audit-governance.md` for the decisions and
`docs/STORAGE_ARCHITECTURE.md` and `docs/AUDIT_ARCHITECTURE.md` for what is
there. It landed in the foundation rather than behind a capability, so every
product has it: `audit_events` left the `reporting` gate, storage records every
upload, download, deletion and refusal, migration `00018_files_governance.sql`
put integrity, classification, retention, hold, scan, archive and backup state
on `files`, `00019_audit_classification.sql` made retention per class, the
provider seam gained listing, copying and digests, the file hooks became a
registry, the quota is checked again at confirmation, and the reconciliation
sweep two comments promised since `00005_files.sql` exists and reports without
deleting.

**It was finished on 2026-09-16 and the shop is level with it.** Object
retention, legal holds, audit search and export, tenant retention overrides,
the governance contract, reconciliation, the expiry sweeps and backup with
digest verification all ship. **Restore ships too, and this line said otherwise
until 2026-09-19** — `00026_restore_requests.sql`, `routers/restore.py`,
`tasks/storage_restore.py`, the `/dashboard/restore` page and
`e2e/restore.spec.ts` are all in the `storage_governance` template map, and the
two-person rule works. The claim was true when ADR 0006 question 3 was open and
outlived the work; `docs/BACKUP_AND_RESTORE.md` has said both halves are built
since 2026-09-16, and the docoris audit found the contradiction independently
and wrote "Believe the code." Recorded rather than quietly corrected, as
PLAT-DEF-002, because this is R-042 landing on the file every session reads
first for the second time. Two independent reviews ran and both
returned BLOCK; every finding is fixed in `1b59f29` and after. `koras-e2e-shop`
carries all of it as of `98d078e`, with migrations 00019-00025 applied to the
dev database and both workflows green.

**The settings framework shipped on 2026-09-19**, in the foundation rather than
behind a capability, so every generated product has it. Three levels — the
platform's default, the organisation's value, the person's preference — and no
fourth. Definitions are declared in Python and registered at import, the way
reports and audit actions already are; values live in three narrow key/value
tables, `global_settings`, `tenant_setting_values` and `member_setting_values`,
each with row-level security enabled and forced and a check constraint that
refuses a secret-shaped key. A new organisation receives a **copy** of the
applicable platform defaults inside the transaction that creates the tenant, and
a later change to a default never reaches an organisation that already exists.
`GET /settings/effective` answers everything in one request, resolved once in
the dashboard layout, and the shared data table reads `grid.*` from there so
that `<KorasDataTable data={records} />` works with no props. The Control Plane
manages the platform defaults through an extended contract — it is not
code-synced, so its half is a parallel implementation against
`contracts/product-platform.v1.json`. `docs/SETTINGS_ARCHITECTURE.md` is the
description.

**Three things about it are worth carrying.** `general.language` replaced two
columns that stored the same fact twice, and doing so produced a rule now in ADR
0007: a setting whose absence means "infer it from context" must express that
inference as one of its values, or the snapshot silently ends the inference —
hence the `auto` value. Five `grid.*` settings ship registered but not drawn,
marked `surfaced=False`, because the shared table does not honour them yet; a
control that changes nothing is worse than one that is not offered. And the
generated product has no page using the shared table, so the page that makes
`grid.pageSize` observable lives in `koras-e2e-shop` and is that repository's
own work rather than a sync.

**The background job contract and in-app notifications shipped on 2026-09-19**,
from the master platform plan in `docs/platform/`. Two things about them are
worth carrying.

**Nothing in this repository could enqueue a background job until that day.**
ARQ was present, the worker ran, nine sweeps were registered — and every one of
them was cron. The three request paths that kept working after the response
used FastAPI background tasks, which run in the API process and are lost when
it restarts. `koras-queue` was a one-line comment file that four services
declared a dependency on. It now carries a task declaration, a job queue that
says whether an enqueue was real, and a wrapper that applies a declared retry
policy — and `tasks/product.py` gained `PRODUCT_TASKS` beside `PRODUCT_CRON_JOBS`,
which answers the question docoris raised as its own OD-19. There is no
dead-letter queue, deliberately: a destination nothing reads is not evidence.
**The seam has no production caller yet**; its first are a notification
dispatch and an import run, and its tests run real tasks through the wrapper
rather than asserting it exists. **Its first caller arrived the same day**: the
import dry run, which is the only enqueue in the repository as of 2026-09-19.

**`notifications` was a capability declared `true` in both manifests that gated
nothing** — no template map, no defaults entry, a two-line package — so
`--without notifications` removed nothing while appearing to succeed. It now
gates a table, a store, four routes, a bell, a drawer, a centre, a sweep and a
browser suite, and `requires` refuses `--with ai --without notifications`. The
assistant's approval notice reaches the product as well as the inbox, in the
same words.

**Phase 2 followed the same day.** `core/dispatch.py` is the single in-process
dispatch point ADR 0008 asked for — no bus — and `core/recipients.py` turns a
rule into people. A producer now names *what happened*, *who should know* and
*how to say it in a language*, and names no channel, table, template or
address. The assistant's approval notice went from resolving its own audience
twice, composing its own HTML and driving its own sender loop to one `dispatch`
call; a notification is written on the caller's session and the mail it
prepares is sent after the commit, because a row can be rolled back and a mail
cannot.

**Two things Phase 2 found are worth carrying.** A recipient's language now
comes from *their own* stored setting rather than from the request — the notice
used to go out in the language of the person who **asked**, who is the one
person it is never sent to. And `notifications.emailEnabled` is
`Scope.GLOBAL_ORG` rather than per person, which is a narrowing rather than an
omission: a mail goes to an address, the product learns addresses from the
platform's member list, and that list carries an email and a role and **no**
ZITADEL subject — so a recipient it can mail is one it cannot match to a
member, and a per-person switch would be a control nothing could ever read.
Offering the rung anyway would have been the same failure `surfaced=False`
exists to prevent. F26 records what the platform would have to answer.

**And six settings were being drawn and read by nothing.** Three under
`notifications` and three under `files`, registered, translated into three
languages, and rendered on the preferences page: a customer could switch off
notification emails and still receive them. That is exactly the failure
`surfaced=False` was introduced to prevent, four days earlier and in the same
file. `notifications.inAppEnabled` was honoured first and `emailEnabled` since Phase
2; `digestFrequency` stays unsurfaced, because a digest needs an outbox to
accumulate into and that is Phase 3. The three `files.*` were still drawn and
enforced by nothing until
the import work took that half on 2026-09-19. Two of them —
`files.maxUploadSizeMb` and `files.allowedExtensions` — are now resolved in
`core/storage.py` and refused at the upload ticket, inside the hardcoded 5 GiB
ceiling rather than instead of it. The third, `files.maxFilesPerUpload`, is
`surfaced=False`: the presign route issues one ticket per call and has no
notion of a batch, so there is nothing for it to count.

Running a freshly generated product's own tests found a second thing: its node
suite was red on `develop`, because the settings framework added a
`preferences` module to the navigation registry the same day and
`navigation.test.ts` asserts the sidebar as an exact list. The starter's suite
was green throughout. Only a generation run closes that gap, which is what
Generator Integration is for.

**What it has not had: a manual pass or an independent review.**
`docs/features/settings-framework/manual-test-plan.md` has fifteen cases and
fifteen blank verdicts as of 2026-09-19, and the first of them — change a page
size, watch a table repaginate — is the thing the feature exists for and the one
no automated test in this estate reaches. The e2e harness starts the web
application alone, so its sixteen browser checks cover routing, refusal and
degraded rendering and nothing that needs an API.

**Data import Phase 1 shipped on 2026-09-19**, as a product capability,
`data_import`, **off by default** — unlike reporting and the governance pair,
because an import target is something a product declares and a product that
declares none would get a page listing nothing. `koras-import` is the engine:
targets, a registry, a CSV reader, a mapping resolver, a row validator and a
ten-state machine, and it knows no table name of any product. The API carries a
run store over `import_runs` and `import_row_errors`, eight routes all behind
`imports.manage` including the reads, and the page is `/dashboard/imports`
behind no plan. `docs/features/data-import/architecture.md` is the description
and `docs/adr/0009-import-runs-are-not-a-third-export.md` is why the run has its
own table.

**What Phase 1 does is stop.** A run reaches `validated`, which is a terminal
state that wrote nothing; there is no commit route, no commit task and no
control on the page that could write a row — absent rather than disabled. That
is asserted structurally rather than behaviourally: the generator's test scans
the run store for every `insert into public.X` and requires X to be one of the
two import tables, so a commit added later without its own confirmation cannot
sail past.

**Three things about it are worth carrying.** The mapping is an allowlist that
*refuses* an undeclared field rather than dropping it, because dropping it is
how an import writes a column it was never meant to reach. A file whose scan is
`pending` or `skipped` is not parsed, which is **narrower than a download** on
purpose — and the consequence is stated rather than hidden: with no scanner
configured every file is `pending`, so a product without one cannot import at
all. And an unconfigured queue is a 503 rather than a 202, because a dry run
that is promised and never happens leaves somebody watching a spinner forever.

**Three Phase 1 plan items were deliberately not built**, and are named in
`docs/features/data-import/architecture.md` rather than left to be
rediscovered: `files.maxFilesPerUpload`, the upload primitive that was to be
extracted into `packages/ui`, and the preview drawn through the shared data
table. None of them touches the safety properties above. No manual pass has run
against any of it, and `koras-e2e-shop` — the one repository in the estate with
a domain that could declare real targets — has not been synced.

**It was reviewed the same day and the review returned BLOCK** — the third in
three, after both governance reviews and the settings one. One critical
finding, two high, three medium, all fixed;
`docs/features/data-import/review.md` is the record.

**The critical one was not in the import feature at all.** `import_runs` was
the only foreign key onto `public.files` in the schema and it was `on delete
restrict`, so the object-retention sweep — which had therefore never met a
refusal and did not handle one — marked the row purged, deleted the customer's
bytes from the bucket, then raised on the row delete and aborted. It met the
same row first on every later run and aborted again, so **no customer file
would ever have been purged again**, silently, and the governance contract
would have gone on answering that retention was configured. The foreign key is
`on delete set null` now, ADR 0009 is amended, and `storage_lifecycle._forget`
makes the sweep survive any row it cannot delete — which is the half that fixes
the class rather than the instance.

**Two of the other five are worth carrying.** `source_bytes` selected
`size_bytes` and never read it, so the whole source went into API memory
bounded by an upload ceiling whose default is five thousand megabytes; it is
64 MiB now, checked before the object is fetched. And `latin-1` sat inside
`ENCODINGS`, where it maps all 256 byte values and therefore cannot raise — so
the decode loop always returned before its own fallback, `replaced` was
structurally always `False`, and a banner written in three languages could
never appear. Its unit test was a disjunction over the flag and could not fail,
which is the more useful half of that finding.

**Both seams were reviewed on 2026-09-20 and the review returned BLOCK** —
the fourth from four independent reviews here, and the rate is not going down.
Neither seam was wrong about what it decided; both were wrong about what they
cost. The dispatch point read all three settings scopes on every call and was
called once per person per channel, so ten approvers cost fifty-four statements
on the request path while somebody waited for an assistant to answer; it is
twenty-four now, of which twenty are the irreducible per-person row read and
feed insert. And the shared table rendered with `table-layout: auto`, under
which a width on a cell is a hint the browser satisfies *after* content — so a
resized column got wider and never narrower, on exactly the columns anybody
would want to narrow, which made `grid.allowColumnResize` a control that half
worked on the day it was surfaced.

**Both classes were invisible to every assertion those seams shipped with**,
because all of them ask what was decided rather than what it cost or whether it
took effect. The regression tests added with the fixes assert a statement count
and a CSS property for that reason. `docs/features/notifications/review.md` has
all six findings.

**`koras-e2e-shop` was brought level on 2026-09-20**, and it had fallen further
behind than one sync: it never received PLAT-F1 or CAT-01 Phase 1 at all, so it
carried a `notifications` capability in `.koras/project.yaml` and none of the
feature — and it had been missing `00033_settings_secret_guard.sql` since the
settings review wrote it. Seventy-eight files, verified at 55 turbo tasks, ruff,
mypy over 133 files and 911 pytest.

**The sync method needed a correction worth carrying.** The three-way compare
assumes the repository's files all come from one starter commit, and they do
not — it is hand-carried file by file, so for nine files the shop's copy was an
*older starter* than the merge base rather than its own work. A three-way merge
reads that as a conflict and invites a wrong resolution. What distinguishes the
two is asking what the repository *added*, not what it differs by:
`diff(base, repository)` showing only removals means there is nothing to
preserve.

**CAT-03 Phase 2b shipped to the Control Plane on 2026-09-20** as
`billing.catalogue`, the reconciliation engine's eighth check: it reads back
every price the platform *offers* rather than only the ones it has sold. The
finding worth the check is a price in the monthly column that recurs yearly —
both sides present, both looking right, the customer billed on a cycle nobody
chose, and nothing else in the estate able to notice.

**Phase 2a was answered on 2026-09-20, and the answer was neither option.**
The plan has a provisioner read the Koras catalogue and create the prices it
names; there was no such catalogue, because `00028_billing.sql` decided that
"what it costs lives with the provider". The catalogue now holds an *intent* — three
nullable columns there recording what a plan was meant to cost — compared by
`billing.catalogue` and rendered nowhere, so the provider stays authoritative
for everything a customer sees or pays. The columns are named in
`koras-control-plane/docs/COMMERCIAL_CATALOGUE.md`; naming them here would be
this repository vouching for another's schema, which the identifier test
rightly refuses. That narrows the rule
rather than reversing it, and closes the one drift the check could not see: an
amount edited by hand in a dashboard.

**No provisioner is built, deliberately.** Creating a price needs a Managed
Payments tax code — a product without an eligible one cannot be sold at all —
a Stripe price is immutable in amount so no two-way sync can exist, and the
by-hand step is three clicks per plan for a catalogue nobody has created in
live mode even once. BILL-GAP-003 is declined with that reasoning rather than
left PLANNED.

**A plan with no recorded intent is unchecked, not clean**, and a test asserts
that distinction. An expectation nobody stated is not a fact about the price.

**The two capabilities are declared.** `audit_governance` and
`storage_governance`, both on by default, and what they gate is the *surface*
rather than the record: only `00025_file_backups.sql` is a gated migration. A
product generated without either still records every event, classifies it,
forgets it on a schedule, refuses a deletion under hold and answers the
platform's governance contract. The rule is written down because breaking it
has happened: a table is gated only when no foundation code and no foundation
migration reaches it, and `audit_events` sat inside the `reporting` gate until
this work, which meant a product without analytics recorded nothing and nobody
noticed.

**Three defects worth remembering, all found by asking what a comparison would
actually compare.** `checksum()` returned a 32-character entity tag for a column
holding 64 hex characters, so integrity could never be verified. The
cross-provider backup wrote bytes without sending the digest, so a copy could
never be more than `copied`. And the storage retention floor does two jobs --
the minimum a tenant may not go below, and the period after which an object is
deleted -- so setting it to one day would have purged every customer file the
night after upload. `docs/RETENTION_POLICY.md` records the last one.

No manual test pass has run against any of it.

**One defect found and not fixed.** The API declares `fastapi>=0.115.0`, and at
exactly 0.115.0 every route returning `None` with a 204 status fails at import
-- `routers/files.py` and `routers/reporting_schedules.py` both have one. CI
resolves higher, so the suite is green by the luck of resolution rather than
because the declared floor works. Found 2026-09-16; it belongs in
`RISK_REGISTER.md`.

**Next step:** `FOLLOW_UPS.md` opens with the order rather than leaving it to be
re-derived. Eight entries are ordered there as of 2026-09-19, the first being
F27 — an independent review of the settings framework, then its manual pass.

This line said "one entry is left" from 2026-09-15 until 2026-09-19, while that
table carried seven rows. It was not a claim anything could check: the count
lives in another file, in prose, and nothing compares the two. That is R-042
exactly, on the file every session reads first, and it is recorded rather than
quietly corrected because the same sentence has now been wrong twice.

**2026-09-15 closed six of them.** F7 (the registration now answers what the
registry stored, and the generator compares, which found two fields accepted and
stored by nothing), F19 (the platform's logos served from the product's own
origin, so the policy stays `img-src 'self'`), F20 (a member's stored language
and a tenant default, `apps/admin`, translated mail and API error codes, and a
`[locale]` segment that makes the marketing homepage a static document again),
F21's test-mode half (recorded fixtures, six browser checkouts found already
done, a subscription schedule exercised on a real subscription), F24 (the
collectors component on platform health, and the decision that Managed Payments
cannot carry the AI overage), and R-042's fourth class.

F13 was decided on 2026-09-01 — trial-only, which was already the behaviour —
and deciding it found that `koras-control-plane`'s entitlement resolver ignored
`subscriptions.status` entirely: a cancelled customer resolved the same
entitlements as a paying one, and a trial could not expire because nothing
expired it either. Fixed there as R-93, awaiting review on PR #2. Nothing was
wrongly ungated, because no product gates on a plan yet — which is exactly why
it had survived since the resolver was written.

Then one live sitting, three things needing the same estate and the same
credentials: R-036's second teardown now that Cloudflare is in the inventory;
the F17 token audience; and one `--register-only` for `koras-e2e-shop`, which
would be the estate's first *confirmed* registration.

F21's test-mode half closed on 2026-09-15. A person paid the checkout an agent
is refused at, and the rest ran on its own — subscription created, provisioning
finished, welcome mail sent, owner's password set. What is left there is live
mode alone.

`koras-e2e-shop` was synced the same day, and by a method worth reusing: a
product was generated from the starter as it was before the day's commits and
as it is after, and the two were compared against the repository three ways, so
a file the shop had written itself could not be silently reverted. Exactly one
file needed a hand — the manifest digest, which is meant to change.

F7 carried a constraint from 2026-09-01 until 2026-09-15: the registration
response returned environment *names*, not stored references, so the identity
that registers could not confirm what the registry held — a payload stored
wrongly and one stored correctly were indistinguishable to the caller. The
Control Plane now answers `stored_environments`, read back inside the
registration's own transaction, and the generator compares it key for key.

This said the `--with` / `--without` paths were untested. They have been tested
since 2026-08-25: `generator-integration.yml` carries an
`--with marketing,ai_gateway,scheduler` row and an `--without admin,worker` row,
each built, linted, typechecked, tested and run through the RLS suite. The claim
outlived the work by four days, in the one file every session reads first.

**What is verified, and how.** The required validation workflows on `develop`
are **CI**, **Security** and **Generator Integration**. That is the list of
gates; it is not a status report.

**Do not infer their current status from this document.** Check the workflow
results for the branch and commit you are actually working on — `gh run list
--branch develop` — before claiming anything about them. This paragraph said
all three were green from 2026-09-05 to 2026-09-12 while all three were red,
and said it again through the five commits before 2026-09-20 while Security
was failing and Generator Integration was being cancelled at its time limit.
Twice is a pattern, and the pattern is that a sentence about a live system
decays the moment it is written. That is R-042 on the file every session reads
first.

**Last validated baseline: 2026-09-20, commit `2d62a82`.** CI passed. Security
failed on one gitleaks finding — `generic-api-key` at `recipients.py:211`,
reviewed as a false positive and suppressed by fingerprint in `dcffeab`.
Generator Integration was cancelled at its 30-minute limit, which read as a
slow suite and was a crash: the notification bell passed a function across a
server/client boundary, so every signed-in page threw and 72+ browser tests
each failed on a 30s timeout. Fixed in `728d916`; the generated product's full
browser suite then passed locally in 1.4 minutes, 137 passed and 0 failed.
**Neither fix had been through CI when this was written** — that is exactly
the claim to verify rather than inherit.

**What Generator Integration actually does**, which is capability rather than
status: it generates both profiles and lints, builds, typechecks and tests
each, runs the row-level security suite against a real Postgres,
mutation-tests that suite by removing `force` and requiring it to fail, and —
since 2026-09-01 — **opens a browser**, running the product template's
Playwright suite against the project it just generated, at 375 and 1440
(FOLLOW_UPS F18). Its browser step is the only thing in this estate that
renders the generated application; the starter's own suites never do, which is
why a defect that broke every dashboard page could pass every local check.

Local `pnpm lint`, `typecheck` and `test` cover Python as well as JavaScript;
they did not until 2026-08-25, and `turbo` was replaying cached results across
template edits until the same day (R-035).

**Registration, in one paragraph.** A product registers itself with the Control
Plane after `terraform apply`, from `generators/create-koras-app/src/registration/`,
and — where a repository variable explicitly enables it — again after every
deployment of an environment, from
`local/scripts/register-with-control-plane.sh` in the shared template. That
deploy-time job is **off by default** (F2b): the only identity that can register
today is the estate-wide `registrar`, and putting it in one product's CI gives
that product write access to every other product's registry entry. Refreshing a
product's references is `--register-only` from the factory instead — read
Terraform outputs and send them, never plan, never apply.

The address comes from Doppler as `KORAS_CONTROL_PLANE_URL`. What authorises the
call is `KORAS_CONTROL_PLANE_KEY_JSON`, the `registrar` service-account key, from
which the generator mints a token per call; `KORAS_CONTROL_PLANE_PROJECT_ID`
names the audience, and the ZITADEL instance is derived from the URL rather than
answered separately. `KORAS_CONTROL_PLANE_TOKEN` is a finished bearer and still
accepted, but it lasts twelve hours, so the key wins when both are set.
`--control-plane-url` overrides the address; nothing overrides the credential. An unconfigured Control Plane is a skip, not a
failure — that is the documented bootstrap order (R-001) — while a
*misconfigured* one is a failure, because a misconfiguration reported as
nothing-to-do is one nobody fixes. A failure never unwinds infrastructure. The
Control Plane profile registers nothing, refused four independent times; the
fourth matters because `deploy.yml` is shared by both profiles and cannot be a
Handlebars template. The contract is
`koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md` and it is
authoritative; `docs/REGISTRATION_LIFECYCLE.md` records what each pass can and
cannot carry, and why.


Caveats when reading the roadmap:

- Phases 11 and 12 now define their exit criteria on `develop` (decided
  2026-08-24). `main` was 85 commits behind and last received a commit on
  2026-08-17, so a criterion defined there could not close on work already
  done. Promotion to `main` is a release step, not a definition of done.
- **The workflows now run** (resolved 2026-08-25). They had zero recorded runs
  across 85+ commits; the cause was Actions billing on a private repository,
  and the repository being public is what makes minutes free. Jobs are observed
  starting and succeeding. **Making the repository private again re-blocks
  every run** and returns each CI-based criterion to unmeasurable — see R-030,
  which reopens rather than being rediscovered.
- The roadmap does not cover R-020 through R-027 or the OIDC sign-in work.
  Roughly twenty commits of deployment and authentication work sit outside the
  phase structure, recorded only in `docs/RISK_REGISTER.md`. Nothing in the plan has
  "a user signs in to a deployed application" as an exit criterion.

`koras-control-plane` keeps a separate Phase 0–19 roadmap. The numbers are not
shared: Phase 12 is Security here and "Domains and branding" there.
