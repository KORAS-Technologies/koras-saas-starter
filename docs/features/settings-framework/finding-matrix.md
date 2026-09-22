# Settings framework — F27 finding reconciliation

| | |
|---|---|
| **Purpose** | What each carried SET finding actually does on the tree in front of us, rather than what the review said about the tree it looked at. One row per finding, one disposition each, and the evidence that produced it. |
| **Reconciled** | 2026-09-21, against `5e8fbc4`. |
| **Method** | Each finding was reproduced by execution wherever a probe could reach it: a product generated from `5e8fbc4`, its own API under FastAPI's test client with the product's own fixtures, and a real PostgreSQL 15 with all 28 of the product's migrations applied and the row-level security suites run as the unprivileged `koras_rls_test` role. Findings no probe can reach are marked as read rather than run, and say so. |
| **Probes** | `docs/features/settings-framework/testing/runs/2026-09-21-01/repro-probe-batch-1.py` and `docs/features/settings-framework/testing/runs/2026-09-21-01/repro-probe-batch-2.py`. Each asserts the **defective** behaviour, so a green run means the finding still reproduces. |

## Why this file exists

`review.md` is the record of what the first independent review found on
2026-09-19. It is not amended here and should not be: a review is evidence
about a moment, and rewriting it to match a later tree destroys the only record
of what was true then.

This is the second document, and it answers a different question — *does it
still do that, and how do we know*. Where the two disagree, this one names the
disagreement rather than quietly winning.

## Summary

| Disposition | Count | IDs |
|---|---|---|
| REPRODUCED, fixed this cycle | 4 | SET-05, SET-06, SET-07, SET-22 |
| REPRODUCED, carried open | 9 | SET-08, SET-09, SET-10, SET-11, SET-14, SET-16, SET-17, SET-18, SET-19 |
| REPRODUCED by reading, carried open | 3 | SET-12, SET-13, SET-15 |
| NOT REPRODUCED as written | 1 | SET-21 |
| Read-only, no behaviour to reproduce | 1 | SET-20 |

**Eleven of eighteen were reproduced by running something.** Nothing was
marked fixed on the strength of code that looked as though it addressed it,
and one finding did not survive contact with the code at all.

## The four fixed

### SET-05 · High · Saving one category creates a personal override for every field in it

**Reproduced** by reading the pair that produces it: every non-boolean control
in `settings-form.tsx` renders with a `defaultValue`, so every one submits on
every save, and `valuesFromForm` walked the definitions and wrote whatever it
was given. A member who changed their theme therefore acquired a personal row
for density, landing page and sidebar as well — detached from their
organisation's defaults for three settings they never touched.

**Fixed** by carrying what each control was drawn with in a hidden
`__baseline.<key>` and dropping any value equal to its baseline. A form with no
baselines writes everything, which is the previous behaviour and the safe
direction to fail in.

**What it gives up, recorded rather than discovered.** A person can no longer
*create* an override whose value equals the one they are inheriting; an
override they already hold is untouched. The two states differ only if the
organisation later changes that setting, and the page offers no other way to
say "pin this". Named in the code at the function that does it.

### SET-06 · High · Every field on a new tenant reads as modified

**Reproduced** from `seed_tenant`, which writes a row for **every**
organisation-scoped definition, and `toField`, which set `isSet` from row
presence. After provisioning, presence is true of every key, so every field on
the organisation page read as modified, none ever read as inherited, and the
marker carried no information at all.

**Fixed** by making what "held here" means a property of the page rather than
of the table. The organisation page asks `differs-from-inherited`; the
preferences page keeps `a-row-exists`, and that asymmetry is the point — a
member row exists only when somebody chose one, so presence *is* the choice
there, and comparing would be wrong for anybody who deliberately picks the
value their organisation already has. That caveat has been in
`SettingField.isSet` since it was written and is still correct; it is now
correct at the one scope where it applies.

**Not fixed by a schema change.** Recording provenance per row would be the
more faithful answer and was declined for this cycle as out of bounded scope.

### SET-07 · High · The effective route discloses what the tenant-values route gates

**Reproduced** by probe: a plain member is refused `GET /tenant/settings/values`
with 403 and, in the same breath, served the organisation's stored value **and
the platform's** for every key by `GET /settings/effective`.

**Fixed in two passes, and the first was not enough.** It withheld
`global_value` from a caller without `settings.read`. The closure review then
pointed out that the permissioned sibling refuses the **organisation's** rows
rather than the platform's — so withholding the platform column moved the
disclosure instead of closing it, and a member could still read what their
organisation had configured for every key.

`organization_value` is now withheld as well, **except where `can_override` is
true**. There it is what that member's own Reset restores, and a control that
cannot say what it would do is worse than the disclosure; everywhere else it
is organisation configuration that no control on either page reads. The
resolved `value` is never withheld — the shell renders from it.

Both pages keep working: the organisation page is reached only with
`settings.manage`, which no role holds without `settings.read`, and the
preferences page reads `organization_value` for settings a person can
override, which is the half that survives.

### SET-22 · High → **Medium** · No isolation suite ever tries to move a row

**Reproduced exactly as written.** Both `WITH CHECK` clauses were replaced with
`true` against a real database and all three suites stayed green.

**The severity is lowered, and the reason is worth carrying.** The finding
implies an unguarded cross-tenant row move. There is none: PostgreSQL applies
the **select** policy to the new row on an update, so a move is refused twice
over. Demonstrated by bisection — with `WITH CHECK` explicitly at `true` the
move is still refused, and it succeeds only when the select policy is *also*
widened. The clause is defence in depth rather than the only guard, so the
exposure was a test gap and not a live hole.

**That mechanism was disputed by the closure review and re-checked rather than
defended.** Three configurations against a real database, recorded in
`docs/features/settings-framework/testing/runs/2026-09-21-01/set22-mutation-bisection.txt`;
the bisection stands.

**The review was right about something else, and it sharpens the finding.**
*Deleting* a `WITH CHECK` clause is not the same as weakening one: `CREATE
POLICY` falls back to the `using` expression when none is given, and here the
two are identical — so the deletion the original finding describes is a
semantic no-op that nothing can or should catch. What the new tests catch is
a clause weakened to something that admits another tenant, which is the edit
that would actually cost something.

**Fixed in two parts, because the obvious fix does not work.** Attempting the
move only proves the *boundary*, and stays green when `WITH CHECK` is deleted —
the select policy does the work. So each suite now also neutralises the select
policy for the length of one statement and attempts the move again, which only
`WITH CHECK` can refuse. Both halves were mutation-tested in both directions:
green on the correct schema, red with the right message when the clause is
removed.

A first draft of this test went red under the mutation for the wrong reason —
a primary-key collision with a row the other tenant already held. It now moves
a key the other tenant does not have, so only the policy can refuse it.

## The twelve carried

None of these is fixed. Each was reproduced or read on `5e8fbc4` and each is
carried with its reason; the register keeps the schedule.

| ID | Sev | Disposition | Evidence |
|----|-----|-------------|----------|
| SET-08 | Medium | REPRODUCED (substituted definitions) | The shipped catalogue declares no `system` or deprecated setting, so the probe registers one of each: both are correctly hidden from `GET /settings/definitions` and both are written by a tenant administrator. The write path consults scope and nothing else. Latent exactly as the review said. |
| SET-09 | Medium | REPRODUCED | A one-megabyte string stored through `PATCH /me/settings`, which needs no permission. `_within_bounds` is numbers only; strings, lists and objects have no size rule. |
| SET-10 | Medium | REPRODUCED | A two-key write produced more than one commit: `record()` flushes, and the sink commits. The values are committed when the first audit event flushes, so a failure writing the third event leaves the settings changed and the trail short. |
| SET-11 | Medium | REPRODUCED | With the platform holding `grid.pageSize` = 5, below the declared minimum of 10, the reset wrote 5 and answered 5, while the resolver skipped it and resolved 50. One rule, two implementations, disagreeing. |
| SET-12 | Medium | REPRODUCED by reading | `write_global_values` computes `global_version() + 1` and then inserts, so two concurrent platform writes take the same number; `global_settings` also carries a delete policy, so the maximum can go down. Not probed: it needs two concurrent sessions, and the finding is not in doubt. |
| SET-13 | Medium | REPRODUCED by reading | `seed_tenant` protects existing rows with `on conflict do nothing`, so a re-seed cannot overwrite a chosen value — but a key added to the catalogue *after* the tenant existed is inserted at today's default, while `where settings_copied_at is null` leaves the recorded provenance naming the original version. The snapshot guarantee is then false for exactly the keys a customer never chose. |
| SET-14 | Medium | REPRODUCED | `write_global_settings` binds the change list to `_written` and discards it; the handler contains no `record(` and no `_audit`. The one write that reaches every tenant created afterwards records nothing. |
| SET-15 | Medium | REPRODUCED by reading | A scope narrowed from three levels to two leaves member rows the resolver will not read (`admits_user` is false) and the clear route refuses to delete (403 `setting_scope_refused`). Neither used nor removable, and nothing reports them. |
| SET-16 | Low | REPRODUCED | `files.allowedExtensions` set to `[]` is accepted and stored. An empty allow-list permits nothing, so uploads are switched off by clearing a text box, with no confirmation. |
| SET-17 | Low | REPRODUCED | `PATCH /me/settings` with an organisation-only key answers 403 and writes no audit row, while the handler's own docstring says the refusal is recorded. |
| SET-18 | Low | REPRODUCED | `skipped` is a list of bare keys. The resolver knows which rung held the bad value and the route drops it, which is the single question an operator needs answered. |
| SET-19 | Low | REPRODUCED | A 5000-character caller-supplied key reached `audit_events.target_id` on the permission-refusal path — from a caller who, by construction, lacks the permission. |

## The two that did not hold

### SET-20 · Low · The `sensitive` flag is published nowhere

**Confirmed as stated, and it is not a behaviour.** `DefinitionView` carries no
`sensitive` field, so no surface can mask one. Nothing leaks today because no
definition sets the flag. Recorded here as read rather than run, because there
is no defective behaviour to execute — only an absent capability.

### SET-21 · Low · **NOT REPRODUCED as written**

The finding is *"two load-bearing comments describe behaviour the code does not
have"*, and names one of them: a comment saying the worker's sweeps carry the
provisioning declaration, *"which they never declare"*.

**They do declare it.** `tasks/ai_retention.py`, `tasks/audit_retention.py` and
`tasks/governance_expiry.py` each hold
`set_config('app.provisioning', 'on', true)` and run on it. The comment in
`00029_settings.sql` that mentions the sweeps is therefore accurate.

The second comment is not identified in `review.md` beyond *"a conflict clause
the statement does not use"*, and the four `on conflict` clauses in
`settings_store.py` each match the prose beside them. Without the reviewer's
line reference there is nothing further to check.

**Carried as OPEN with the severity unchanged and the disposition corrected**,
rather than closed: one half is demonstrably wrong about the code, and the
other half cannot be located from what was written down. The useful lesson is
about the record rather than the code — a finding that does not cite a line
cannot be reconciled by anybody but its author, which is a cost worth knowing
before the next review.

## One finding from outside this set

**SET-23 · High · two accessibility settings offered and read by nothing.**
Found by G7 R2 on 2026-09-21, a day before this reconciliation, and inside
F27's own catalogue. One third was closed by G7R2-F01, which wired
`accessibility.highContrast` to the shell. `accessibility.reducedMotion` and
`accessibility.fontScale` remained surfaced, translated into three languages,
drawn on the preferences page and honoured by nothing.

Treated as in scope for closure, because an applicable unresolved HIGH forbids
it and because this is the precise defect `surfaced=False` was introduced to
prevent — twice now, in the same file, four and two days apart.

**Both are now `surfaced=False`**, with their six translations removed, which
is the remedy the grid pair and the notification digest already carry.
Honouring them is a Settings story rather than a correction, and is not done
here.
