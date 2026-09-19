# Master capability matrix

| | |
|---|---|
| **Purpose** | For every platform capability the three feature categories touch: whether it exists, where it lives, who needs it, what is wrong with it, and what to do. Established by reading the repository on 2026-09-19, not by reading its claims about itself. |
| **Surveyed** | 2026-09-19, against `develop` at `f198908`, product migrations `00001`–`00031`. |
| **Companion** | `docs/platform/gap-defect-register.md` carries the numbered findings; this carries the verdicts. |

## The one structural fact to read first

**The starter's root `packages/`, `services/`, `apps/`, `python-packages/` and
`supabase/` are empty.** Every line of runnable code lives in one of three
template layers, rendered in this order, later winning on a shared path:

```
profiles/_shared/template/      walked first   — both profiles
profiles/product/template/      walked second  — the product profile
profiles/control-plane/template/               — the control-plane profile
```

Any capability in this matrix is delivered as a template change plus a manifest
entry, a defaults entry, a template-map entry and a generator test. Nothing in
this repository is deployed; it is generated.

**A package directory name is not a capability.** Eleven TypeScript packages
are two-line stubs: billing, domains, feature-flags, notifications, storage,
audit, security, observability, validation, types, and email (the last
deliberately, with its reason written in the file). The substance is Python
under `services/api/koras_api/` and `python-packages/koras-*`, plus
`packages/branding`, `packages/permissions`, `packages/auth`, `packages/ui`,
`packages/i18n` and `packages/api-client`.

## Verdict vocabulary

`EXISTS` · `EXISTS + EXTENSION POINT` · `PARTIAL` · `MISSING` · `DUPLICATED` ·
`CONFLICTING` · `NEEDS_REFACTOR`. A `MISSING` verdict was established by a
search that returned nothing, not by not having found it.

---

## 1. Foundations every category rests on

| Capability | Status | Where it lives | Reusable | Used by | Problem | Action |
|---|---|---|---|---|---|---|
| **Auth / identity** | EXISTS | `python-packages/koras-auth`, `core/auth.py`; OIDC against ZITADEL, JWKS cache, issuer, audience and client all checked, 401 kept distinct from 403 | Yes, as is | All three | None found | Reuse unchanged |
| **Tenant context** | EXISTS | `python-packages/koras-tenant`, `koras-database`; three declaration types, transaction-local settings, bound values, `UndeclaredCaller` on an undeclared transaction | Yes, as is | All three | None found | Reuse unchanged. Every new table gets forced RLS and an isolation test |
| **RLS enforcement** | EXISTS | Every table `enable` **and** `force`; API and worker both refuse to start on a connection RLS cannot restrain | Yes, as is | CAT-01, CAT-02 | None found | Reuse unchanged |
| **Permissions** | EXISTS + EXTENSION POINT | `packages/permissions/src/index.ts` and `koras_auth/permissions.py`; 16 strings, derived from the closed organisation role set, mirrored in two languages and kept level by a generator test | Yes | CAT-01, CAT-02 | No grant store and no per-object authorization — a real limit, outside these categories | Add one string per category, in both languages, plus a route that checks it |
| **Entitlements** | EXISTS + EXTENSION POINT | `packages/branding` parses; the Control Plane resolves, with the caller's own token; `tenant_plans` caches for the worker | Yes | CAT-03 primarily | Unresolved means not entitled, which is the safe direction | Reuse. CAT-03 owns the catalogue behind it |
| **Settings** | EXISTS + EXTENSION POINT | `python-packages/koras-settings`, three tables, snapshot per organisation, one effective read per request; the extension point is the empty product settings list | Yes | All three | **PLAT-DEF-001**: six settings surfaced and read by nothing | Reuse the framework; fix the six |
| **Audit** | EXISTS + EXTENSION POINT | `python-packages/koras-audit`; a frozen envelope refusing credential-shaped detail keys, an action registry raising on an unregistered key, four classes, per-class retention swept nightly | Yes | All three | **NOTIF-DEF-002**: the one transactional mail records nothing | Register an action per category; never log verbose worker output as audit |
| **Storage** | EXISTS + EXTENSION POINT | `python-packages/koras-storage`; a nine-method provider protocol, one S3 implementation, a closed eight-value category enum in the key, a three-step upload ticket with the quota re-checked at confirmation, a file-hook registry | Yes | CAT-02 | Scanning is a seam with no scanner; no multipart above 5 GiB | CAT-02 uses the unused imports category and refuses to parse an unscanned file |
| **Object storage governance** | EXISTS | Retention, legal holds, reconciliation, backup, restore — all shipped, each destructive sweep separately off until a setting asks for it | Yes | CAT-02 | **PLAT-DEF-002**: `CLAUDE.md` said restore does not ship | Nothing to build; import artefacts inherit it |
| **Background execution** | **PARTIAL** | ARQ worker, cron only; a product cron extension point; FastAPI background tasks in three request paths | **No** | CAT-01, CAT-02 | **PLAT-GAP-001**: nothing can enqueue a job. **PLAT-GAP-002**: the queue package is a stub four services depend on. **PLAT-GAP-003**: no retry or dead-letter policy | **PLAT-F1 — build the job contract first.** The single hard blocker in this plan |
| **Transactional outbox** | MISSING | — | — | CAT-01 | **PLAT-GAP-004** | CAT-01 Phase 3 |
| **Domain event bus** | MISSING | — | — | CAT-01, CAT-02 | **PLAT-GAP-005** | Deliberately deferred; one in-process dispatch point instead |
| **Scheduler service** | PARTIAL | `services/scheduler`, two jobs with `pass` bodies | No | — | **PLAT-GAP-008** | Not used by any category; the real periodic work is worker cron |
| **Observability** | PARTIAL | OpenTelemetry traces, structured logging, rate limiting with quota headers, liveness | Partly | All three | **PLAT-GAP-007**: no metrics, no readiness probe, no correlation id | Each category defines what it would emit; none builds a second telemetry stack |
| **i18n** | EXISTS + EXTENSION POINT | `packages/i18n` (en, de, es), member and tenant preference through the settings framework, localised mail catalogue and API error codes | Yes | CAT-01, CAT-02 | **NOTIF-DEF-003**: mail is composed in the sender's language, not the recipient's | Every new key lands in all three catalogues; a generator test enforces it |
| **Navigation / app shell** | EXISTS + EXTENSION POINT | `packages/branding` navigation registry; the middleware and the sidebar read the same registry, so a hidden link and a refused URL cannot drift | Yes | CAT-01, CAT-02 | None found | One module literal per new page; the page still refuses on its own |
| **Shared data table** | PARTIAL | `packages/ui/src/data-table`; client-side paging, reads five grid settings | Partly | CAT-02 | **IMPORT-GAP-006**: no server pagination, sort, filter, selection or loading state | CAT-02 works within it in Phase 1; lifting the state is a shared-component change with a named owner |
| **Upload UI** | PARTIAL | One hidden single-file input on the Files page with digest-then-ticket-then-progress | Partly | CAT-02 | **IMPORT-GAP-007**: no shared primitive, no drag and drop, no multi-file | CAT-02 Phase 1 extracts the existing flow rather than writing a second |
| **Registry convention** | EXISTS, six times | Reporting, audit actions, settings, file hooks, AI, navigation | Yes | CAT-01, CAT-02 | **PLAT-DEBT-002**: the convention is written in six docstrings and nowhere else | Write it down once before adding the seventh and eighth |

---

## 2. CAT-01 Notifications

| Capability | Status | Where | Used by | Problem | Action |
|---|---|---|---|---|---|
| Email transport | EXISTS | `python-packages/koras-email`: a sender protocol, an SMTP sender on the standard library, a recording sender when no host is configured, transient and permanent errors kept apart | CAT-01, CAT-02 | Provider-agnostic by design — it speaks SMTP, and Resend, Postmark and SES all do | Keep. It becomes the first channel adapter |
| Mail message catalogue | PARTIAL | `koras_email.i18n`, sixteen keys in three languages | CAT-01 | Fourteen of the sixteen belong to one feature | Generalise with the template registry |
| Transactional templates | PARTIAL | One, composed inline in `core/notify.py` | CAT-01 | **NOTIF-GAP-002**: no registry, no layout, no catalogue | Phase 2 |
| Recipient resolution | PARTIAL | One function, one event, one hardcoded permission | CAT-01 | **NOTIF-GAP-004** | Phase 2 |
| Channel abstraction | MISSING | — | CAT-01 | **NOTIF-GAP-003** | Phase 2 |
| In-app notifications | MISSING | — | CAT-01, CAT-02 | **NOTIF-GAP-001** | Phase 1 |
| Toast | MISSING | Roughly thirty hand-rolled live regions; no toast library anywhere | CAT-01, CAT-02 | **NOTIF-GAP-007** | Phase 1 |
| Banner / message bar | PARTIAL | The subscription notice is a card, not a dismissible banner, and is the only thing close | CAT-01 | **NOTIF-GAP-007** | Phase 1 |
| Preferences | **CONFLICTING** | Three settings registered, translated, drawn — and read by nothing | CAT-01 | **NOTIF-DEF-001 / PLAT-DEF-001** | Unsurface now, honour in Phase 2 |
| Delivery log | MISSING | The message id is returned by the sender and dropped at both call sites | CAT-01 | **NOTIF-GAP-005** | Phase 3 |
| Retry / dead letter | MISSING | — | CAT-01 | **PLAT-GAP-003** | PLAT-F1 then Phase 3 |
| Deduplication | MISSING | The mail package's docstring states delivery is at-least-once and that the caller must arrange otherwise | CAT-01 | **PLAT-GAP-004** | Phase 3, by the outbox row |
| Digests | MISSING | A setting offers three frequencies; no job reads it | CAT-01 | **NOTIF-GAP-009** | Phase 4 |
| Announcements | MISSING | Nothing in either repository | CAT-01 | **NOTIF-GAP-008** | Phase 4 |
| SMS | MISSING | Verified by search | CAT-01 | **NOTIF-GAP-006** | Phase 5 |
| Realtime | PARTIAL | Server-sent events exist, for the assistant only; no WebSocket, no Supabase realtime channels | CAT-01 | **PLAT-DEF-005** names the manifest claim | Phase 1 polls the unread count; streaming waits for evidence it is needed |
| The capability flag | **CONFLICTING** | Declared true in both manifests, gates nothing | CAT-01 | **PLAT-DEF-006** | Phase 0 gives the name a template map |

---

## 3. CAT-02 Data Import

| Capability | Status | Where | Used by | Problem | Action |
|---|---|---|---|---|---|
| Import engine | MISSING | — | CAT-02 | **IMPORT-GAP-001** | The whole category |
| CSV / XLSX / JSON reading | MISSING | The only workbook reader extracts text for embeddings | CAT-02 | **IMPORT-GAP-003** | Phases 1 and 3 |
| Export engine | EXISTS + EXTENSION POINT | `python-packages/koras-reporting`: definitions, registries, typed filters with no free-text kind, a pure visibility rule, CSV, XLSX and PDF writers with a spreadsheet-formula defence on every cell | CAT-02 | None found | **The closest analogue in the repository. Copy its shape rather than inventing one** |
| Background export | DUPLICATED | Two independent implementations — report exports and audit exports — each with its own table, status set, expiry sweep and download route | CAT-02 | **PLAT-GAP-006** | Decide before designing the import tables whether import is a third instance or the reason to extract the shape |
| Object storage for artefacts | EXISTS | The imports category is already in the closed enum, unused | CAT-02 | **IMPORT-GAP-002** | Use it |
| Upload ticket | EXISTS | Presign, client PUT, confirm with the quota re-checked and the client digest corroborated | CAT-02 | Ceiling is hardcoded; the three file settings are ignored | **IMPORT-DEF-001**: enforce them at presign |
| Malware scanning | PARTIAL | A seam, a status enum, a quarantine path, and no scanner | CAT-02 | **IMPORT-GAP-011**: a pending file may be downloaded by design | Refuse to *parse* pending or skipped, which needs no scanner |
| Field mapping | MISSING | — | CAT-02 | **IMPORT-GAP-004** | Phases 1 and 3 |
| Validation | PARTIAL | `packages/validation` is a stub; real validation is per-route Pydantic | CAT-02 | One schema should serve the single-record route and the import row | Phase 1 shares the row schema with the route that already exists |
| Row-level errors | MISSING | — | CAT-02 | **IMPORT-GAP-005** | Phase 2 |
| Chunking / resumability | MISSING | No skip-locked cursor anywhere; 300-second job timeout | CAT-02 | **IMPORT-GAP-009** | Phase 4; ahead of it, bound the run and refuse (2026-09-19) |
| Cancellation | MISSING | — | CAT-02 | **IMPORT-GAP-010** | Phase 3 |
| Idempotency | PARTIAL | Two migrations carry idempotency constraints; there is no job-level mechanism | CAT-02 | Retrying a commit must not duplicate committed rows | Phase 2: a natural key per target plus an atomic commit per run |
| Import permission | MISSING | Sixteen strings, none for importing | CAT-02 | **IMPORT-GAP-008** | Phase 1 |
| Progress reporting | MISSING | The only progress in the repository is client-side upload progress | CAT-02 | — | Phase 2, as counts on the run row |

---

## 4. CAT-03 Stripe provisioning

**The ownership finding that reshapes this category.** All billing code lives
in `koras-control-plane`. The starter holds the design document, the signup and
checkout *frontend* templates, the entitlement *reader*, and a `packages/billing`
that is three lines long and which `docs/BILLING_DESIGN.md` says may be removed.
That is not an oversight: the same document states that no product ever holds a
provider credential and no product ever calls the provider. **CAT-03 is
therefore a Control Plane category, and the starter-first rule does not apply to
it** — applying it would move a secret key into every generated repository.

| Capability | Status | Where | Problem | Action |
|---|---|---|---|---|
| Koras product catalogue | EXISTS | Control Plane: plans, a three-tier entitlement model (catalogue, per plan, per subscription), subscriptions, console and portal pages over all three | None in the model | Remains the system of record |
| Entitlement resolution | EXISTS | A single SQL fold, per field not per row, with subscription liveness expressed in the SQL itself so a caller who forgets it gets an error rather than a full set | Fixed as R-93 on 2026-09-01, when a cancelled customer resolved what a paying one did | Reuse unchanged |
| Entitlement seeding | **CONFLICTING** | A migration seeds five reporting codes; the in-code catalogue that seeds a newly registered product does not carry them | **BILL-DEF-001**, **BILL-DEF-002** | Phase 1: one source, or a seed that reads the table |
| Provider adapter | EXISTS | A six-operation protocol naming no vendor, with one HTTP implementation pinned to an API version, form-encoded, no SDK | None in the shape | Extend with two operations for product and price creation |
| Webhook handling | EXISTS | Signature verified, replay window bounded, the event stored before it is acted on, five outcomes all answered 200, out-of-order resolved by occurrence time | None found | Reuse unchanged |
| Checkout | EXISTS | Hosted session opened at verification; provisioning starts on the subscription-created event | None found | Reuse unchanged |
| Price amounts | EXISTS | Read live from the provider, cached ten minutes including negative caching, so a provider outage renders "price at checkout" rather than a 500 | None found | Reuse unchanged |
| Lookup keys | MISSING | Raw price ids only | **BILL-GAP-001** | Phase 1 |
| Outbound idempotency | MISSING | No idempotency key on any call | **BILL-GAP-002** | Phase 1 |
| Product / price provisioning | MISSING | Created by hand in the dashboard, ids pasted into the console | **BILL-GAP-003** | Phase 2 |
| Drift detection | PARTIAL | A subscription check with automatic repair runs every fifteen minutes; no catalogue check | **BILL-GAP-004** | Phase 2 |
| Price versioning | MISSING | One monthly and one yearly id per plan | **BILL-GAP-005** | Phase 3 |
| Multiple currencies | MISSING | No currency in the catalogue's price columns | **BILL-GAP-006** | Phase 3 |
| Environment isolation | EXISTS | A live key is refused outside production and a test key inside it, at construction | None found | Reuse; extend the guard to the provisioner |
| Secrets | EXISTS | Two provider secrets, Control Plane only, in Doppler; the starter names them only to say no product holds them | None found | Reuse unchanged |
| Terraform ownership | MISSING, correctly | No Terraform in either repository manages the provider | None — this is the right boundary | Keep it. Terraform owns infrastructure; the catalogue owns commerce; the provisioner owns the provider |
| Generator involvement | MISSING, correctly | Provisioning is nine Terraform phases, a git push and a registration; the registration payload carries no commercial field | None | Keep it. Plans are seeded server-side at registration |
| Live mode | MISSING | Test mode carries a catalogue, an endpoint, six completed browser checkouts and recorded fixtures | **BILL-GAP-008** | `docs/FOLLOW_UPS.md` F21 owns it; it is not code |

---

## 5. What each category may treat as solved

A category lead reading only its own manifest should take these as given, and
should not re-audit them:

- **Identity, tenancy and RLS.** Every table gets `tenant_id`, forced RLS, four
  policies and a numbered isolation test. The API and the worker both refuse to
  start on a connection that could bypass it.
- **Audit.** Register the action, record the event, never invent a
  classification, never put a credential-shaped key in the detail map.
- **Settings.** Declare the definition in the product settings list, read it
  through the resolver, and if nothing reads it yet, mark it unsurfaced.
- **Storage.** Presign, confirm, signed download. The key shape is fixed and
  the category enum is closed.
- **i18n.** Three catalogues, every key in all three, enforced by a test.
- **Navigation.** One module literal; the middleware reads the same registry.
- **Reporting.** If the feature has numbers worth showing, they are a report
  definition in the product extension point, not a new page.

And these are **not** solved, and a category that needs one must either build it
under PLAT-F1 or state that it does without:

- Enqueueing a job.
- Retrying one.
- Recording that a message was sent.
- Drawing a table the server paginates.
- Emitting a metric.
