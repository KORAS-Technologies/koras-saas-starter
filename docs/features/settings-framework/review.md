# Settings framework — independent review

| | |
|---|---|
| **Purpose** | The record of the first independent review of the settings framework: what was looked at, what was found, what was fixed on the day, and what was not. |
| **Reviewed** | 2026-09-19, the day the framework shipped. |
| **Asked for by** | `docs/FOLLOW_UPS.md` F27, which ranked it first with the reason: *a review's value decays as work is built on top of what it would have found*, and the notification work had just built on it. |
| **Method** | Two reviewers, working independently and in parallel, neither seeing the other's report nor the reasoning of the session that wrote the code. One took security and the data model; one took correctness, the API and the frontend. |

## Verdict

**Both returned BLOCK.** That is the third and fourth independent review this
repository has commissioned, and the third and fourth BLOCK: the two reviews of
the storage and audit governance work both returned BLOCK and every finding was
real. The pattern is now consistent enough to plan around — **code here that
has not been independently reviewed should be assumed to carry defects of this
class**, and a schedule that does not budget for the review is a schedule that
has budgeted for the rework instead.

Twenty-one findings. Two Critical, five High, eight Medium, six Low. Four were
fixed the same day; the rest are below and carried in
`docs/platform/gap-defect-register.md`.

**What the review vindicated matters as much as what it found.** Row-level
security is the strongest part of this work: the reviewer went looking
specifically for an `UPDATE` policy with no `WITH CHECK` — the class that lets
a row be rewritten out of its own tenant — and found all three correct. The
coercion layer handles `bool`-before-`int` in all three places it matters,
which is the most commonly missed defect in that shape of code. No route
accepts a caller-supplied tenant id or subject. All SQL is parameterised.

## Fixed on 2026-09-19

### SET-01 · Critical · A plain member could not use their own preferences page

`GET /settings/definitions` required `settings.read`, and
`ROLE_PERMISSIONS[MEMBER]` does not carry it. That route is the only source of
the metadata the preferences page renders a control from, and the page swallows
the failure — so every plain member, which is most of every tenant, opened
their own preferences and was told the settings were unavailable.

The permission was reasoned about carefully for `/settings/effective` and for
the writes, and applied here by symmetry with a route it is not symmetric with.
This one publishes **build metadata**: the same names, types, bounds and i18n
keys for every customer of the product, holding nobody's values.

**Fixed** by removing the permission. `TenantDep` remains and is the whole of
the protection a list of setting names needs. `GET /tenant/settings/values` —
which does disclose an organisation's configuration — still requires
`settings.read`, and a test now asserts both halves.

### SET-02 · High · The one setting the framework was built to demonstrate could not be changed

`grid.pageSize` was declared `INTEGER` with `ui=SELECT` and **no options**. An
integer cannot carry options; the form renders a select from `field.options`;
so it drew an empty dropdown showing nothing. A select with no selected option
submits no entry at all, so the value could never be changed from either page.

The declaration's own comment says "with the five options below", and nothing
ever read `grid.pageSizeOptions` into the control.

**Fixed** twice over. `grid.pageSize` is a number control, whose bounds already
exist. And a definition drawn as a select with no options is now refused at
import — this module's stated design property, applied to the one rule it was
missing.

### SET-03 · Critical · The secret guard looked one level deep and said it looked everywhere

The guard used `jsonb_each`, which yields the top-level members of an object
and nothing else. Confirmed against a real Postgres before the fix was written
— `true` means "holds no secret", so all three were stored:

```
setting_holds_no_secret('x.config', '{"auth":{"token":"ghp_x"}}')   -> true
setting_holds_no_secret('x.config', '[{"secret":"s"}]')             -> true
setting_holds_no_secret('x.config', '{"a":[{"b":{"apiKey":"s"}}]}') -> true
```

The framework supports an object-valued setting, so this was reachable: an
administrator storing an integration's configuration with a nested auth token
had it accepted, written in plaintext, and then served to every member of the
tenant by the effective-settings route, which needs no permission.

**Fixed** in `00033_settings_secret_guard.sql`, walking the whole document.
Three details cost a run each and are written into the migration: the key-value
method raises on a scalar; silent mode suppresses that and returns **NULL**,
not false; and a check constraint treats NULL as satisfied — so without a
`coalesce` the guard would have passed everything while looking correct.

### SET-04 · High · The word list missed the commonest credential nouns

`integrations.webhookSigningKey` was accepted at every level: it contains none
of the original nouns, and the `key` group required one of exactly four words
before it.

**Fixed** in the same migration: signing, encryption and ssh join the list.
`key` on its own is still deliberately not a word, because `shop.sortKey` is a
column name and a guard that refuses the honest case is a guard somebody turns
off.

**And the suite now asserts the four cases that used to pass**, plus four
legitimate values it must not refuse — including the scalars, which are what
the NULL trap turns on. A suite that only tests what a guard already catches
will keep passing while the guard is wrong, which is what happened here.

## Found and not fixed

Each is carried in `docs/platform/gap-defect-register.md`. They are not fixed
because each is a decision or a redesign rather than a correction, and making
five of those in the same hour as the corrections is how a review becomes a
rewrite.

| ID | Severity | Finding |
|---|---|---|
| SET-05 | High | **Saving one category creates a personal override for every field in it.** The form walks the definitions rather than the submitted fields — necessary for checkboxes, which submit nothing when unchecked, and wrong for everything else. A member who changes only their theme is permanently detached from their organisation's density, landing page and sidebar defaults. |
| SET-06 | High | **The "somebody chose this" marker and the provisioning snapshot are incompatible as designed.** Seeding writes a row for every organisation-scoped key, so every field on a brand-new tenant shows as modified with a reset button, and none ever shows as inherited. |
| SET-07 | High | **The effective-settings route discloses what the tenant-values route gates.** It carries the organisation's stored value and the platform's for every key, to a caller with no permission; the sibling route refuses that same caller. The permission is therefore decorative. |
| SET-08 | Medium | **`system` and deprecated status are enforced on display and nowhere else.** No write path checks either, so a system definition — the documented way to say "the platform sets this on their behalf" — is writable by a tenant administrator. Latent: the shipped catalogue declares none. |
| SET-09 | Medium | **No size bound on strings, lists or objects.** Bounds apply to numbers only. Any member, with no permission, can store an arbitrarily large value and have it echoed in every subsequent effective-settings response. |
| SET-10 | Medium | **The audit helper commits, so a multi-key write is not atomic with its own trail.** The values are committed when the first event flushes; a failure while writing the third leaves four changed settings and two events. |
| SET-11 | Medium | **A reset announces one value and writes another.** The resolver validates the platform row and falls back to the definition default; the reset path does not validate. One rule, two implementations, disagreeing. |
| SET-12 | Medium | **The global version is not monotonic and is read-then-written.** Two concurrent platform writes take the same number; seeding reads version and values in two statements; and an unused delete policy means the maximum can go down. |
| SET-13 | Medium | **Re-seeding pushes today's defaults into an existing tenant** and leaves the recorded provenance saying otherwise, so the snapshot guarantee is false for exactly the keys a customer never chose. |
| SET-14 | Medium | **The platform write route is unaudited and has no caller.** The one write that reaches every tenant created afterwards records nothing; the diff is computed and discarded. |
| SET-15 | Medium | **A scope narrowed in a deploy leaves rows that can be neither used nor deleted**, and nothing reports them. |
| SET-16 | Low | **A string list has no emptiness or duplicate rule.** Clearing "Allowed file types" stores an empty list, which permits nothing — uploads switched off by an empty text box with no confirmation. |
| SET-17 | Low | **A refusal the docstring says is recorded is not.** |
| SET-18 | Low | **Skipped values are reported as bare keys**, so an operator cannot tell which rung holds the bad value — the single question they need answered. |
| SET-19 | Low | **Caller-supplied strings reach the audit table on the permission-refusal path**, unvalidated and unbounded, from a caller who lacks the permission. |
| SET-20 | Low | **The `sensitive` flag is honoured in exactly one place** and is not published, so no surface can mask a field. Nothing leaks today because no definition sets it. |
| SET-21 | Low | **Two load-bearing comments are wrong.** One says the worker's sweeps carry the provisioning declaration — they never declare it. One describes a conflict clause the statement does not use. |

## Gaps in the isolation suites, named by the review

- **No suite ever tries to move a row.** All three `WITH CHECK` clauses are
  correct and entirely unexercised: deleting any of them would leave the suites
  green. The honest finding is that the schema is right and the tests do not
  defend it.
- Two suites have no provisioning block, so two boundaries asserted in prose
  rest on the absence of a policy — exactly the kind of absence somebody adds
  back.
- Two have no "tenant declared, no subject" case, which is the one the third
  does best.
- One never exercises the upsert, which is the statement the API actually
  issues.

## What the manual pass found

**NOT EXECUTED.** `docs/features/settings-framework/manual-test-plan.md` has
fifteen cases and fifteen blank verdicts, unchanged. The first of them — change
a page size, watch a table repaginate — is the one no automated test in this
estate reaches, and it needs a running stack, a signed-in person and a browser.

Worth stating plainly rather than leaving implied: **this review is half of
F27, and the half a machine can do.** It is also the half that found SET-02 —
a defect a person doing case one would have found in thirty seconds, because
case one is opening the control that does not work.
