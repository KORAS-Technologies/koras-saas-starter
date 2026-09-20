# ADR 0009 — An import run is not a third export

**Status.** Accepted, 2026-09-19. The decision CAT-02 Phase 0 owed itself before
any migration was written, recorded as PLAT-GAP-006 in
`docs/platform/gap-defect-register.md`.

**Context.** This repository already has the same pattern twice, built
independently:

- `report_exports` (`00014_report_schedules.sql`) — a row inserted before the
  artefact, `pending` → `ready` | `failed`, a storage key set when the object
  lands, a row count, a safe error sentence, and a signed download minted per
  request.
- `audit_exports` (`00022_audit_exports.sql`) — the same seven ideas, the same
  three states, plus an expiry and a sweep that retires it.

Neither imports anything from the other. The second was written by reading the
first.

Data import needs a table of the same family: a row that outlives the request,
a status a person can find, an artefact written later. Three instances is the
point at which a pattern is either extracted or the duplication is chosen on
purpose, and choosing it by not noticing is how a repository ends up with four.

**Decision.** **Do not extract.** `import_runs` is its own table, and the two
export tables stay as they are.

**Why.** The two exports share more than a shape — they share a *meaning*: ask
for a file, wait, fetch it. Every column follows from that. An import run does
not mean that, and three of its properties say so:

- **It has a lifecycle, not a wait.** An export is `pending` until it is
  `ready`. A run is created, mapped, validated, confirmed, committed — and may
  be cancelled or retried from several of those. Ten states against three, and
  the states are the feature: the dry run *is* a terminal state that wrote
  nothing.
- **It has two actors.** Somebody uploads and maps; somebody confirms. An
  export has one `requested_by` and needs no second.
- **Its artefact is optional and is an output of failure.** An export exists to
  produce a file. A run produces an error file only when there are errors, and
  a run with no errors produces nothing to download at all.

A common ancestor over the three would have to hold a status vocabulary that
fits none of them, an actor column that is null for two thirds of its rows, and
an artefact that is the point for two of the three and an exception for the
third. That abstraction is worse than the duplication it removes.

**What this decision does not settle.** `report_exports` and `audit_exports`
remain duplicates *of each other*, and that is a real thing with a real cost —
the expiry sweep exists for one and not the other, and nothing says whether
that is a decision or an omission. This ADR does not resolve it; it declines to
let a third, differently-shaped table be the reason to. PLAT-GAP-006 stays open
against those two.

**What import borrows rather than inherits**, named so the reuse is visible
without a shared base:

- **The row before the artefact.** The run row is committed before any work
  starts, so a process that dies half way leaves something a person can find
  rather than a request that vanished.
- **The storage key, never a URL.** A signed URL is a bearer credential and is
  minted per request.
- **A safe error sentence**, never a stack and never a provider body.
- **An expiry on the artefact**, as audit exports have and report exports do
  not: an error file carries the customer's own rows and should not sit in a
  bucket because somebody clicked once.

**Consequences.** One more table in the family and no shared base class. A
fourth subject of this shape should re-open the question rather than copy a
third time — and should read this first, because the argument above is about
meaning and not about column overlap, and a fourth table that *does* mean "ask
for a file, wait, fetch it" belongs with the exports rather than with the runs.
