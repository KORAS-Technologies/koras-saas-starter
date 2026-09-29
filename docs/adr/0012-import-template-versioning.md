# ADR 0012 — Import templates: what a template carries, and how a file is judged against a target

**Status.** Accepted, 2026-09-29. The decision
`docs/features/data-import/templates-and-formats-analysis.md` §18 owed itself
before any template was rendered (D6), and the record of the eleven other
decisions that analysis put to the owner the same day, each of which is
resolved below rather than in a file that would have to be re-read.

**Context.** A generated product lets a customer upload a file, map its
columns and commit it through a writer the product declares. Nothing gave the
customer a file to start from. A downloadable template is a file rendered from
the target declaration — the same `FieldSpec` list the validator reads — so
that a person filling it in produces a file the importer already understands.
Once such a file exists, the importer has to answer a question it never had to
answer before: *is this file the template I gave you, and is that template
still the shape of the target?*

Three things are easy to conflate there and must not be:

1. **Template identity** — which rendering of which target, at which version,
   this file came from.
2. **The product's import-definition version** — an integer the product bumps
   when a field's *meaning* changes, which the engine cannot detect.
3. **Structural compatibility** — whether the file's header can be mapped onto
   the target as declared today, whatever it came from.

A file a customer exported from another system carries none of the first two
and may be perfectly compatible. A file rendered from last month's template
carries both and may be incompatible. Neither case is an error in itself.

**Decision.**

- **A target declares `version`**, an integer the product owns, default 1.
  The engine never bumps it. A product bumps it when a field changes meaning:
  a renamed field, a narrowed set of options, a type change. A field added
  as optional is compatible with every older file and needs no bump.
- **The engine computes a fingerprint** over the declared fields — name, kind,
  required, options, in declaration order — as the first twelve hex digits of
  a SHA-256. It changes when the shape changes, whether or not the product
  bumped the version, so a template rendered from a target that changed
  without a bump is still recognised as a different template.
- **A template's identity is `target key / version / fingerprint`.** It is
  written where a person can read it and where a machine can read it, and in
  the CSV it is written nowhere.
- **XLSX carries the identity as a custom document property**, which is
  outside every cell, survives a save from Excel and LibreOffice, and does not
  interfere with the sheet the customer fills. The Instructions sheet repeats
  it in prose. The reader takes the property when present and ignores its
  absence.
- **CSV carries no metadata.** A comment line, a second header or a magic
  cell would each break the one property a CSV template must keep: that it
  opens in any tool as a plain table. A CSV is judged by its header alone.
- **Compatibility is judged from the header for every format**, by one
  function: every required field present under its own name means
  `compatible`; every required field present and other columns besides means
  `unknown_columns`; a required field absent means `incompatible`. The
  mapping page still lets a person map a compatible-with-unknown-columns file
  by hand, and refuses an incompatible one by name at mapping time exactly as
  it did before this decision — the verdict tells a person *why* before they
  reach that refusal.
- **A structurally compatible ordinary CSV is never refused for lacking
  template metadata.** The verdict is information; the mapping is the gate.
- **A file whose XLSX property names an older version or a different
  fingerprint is reported as such** in the analysis, with the version it
  found, so a person is told their template is out of date. It is not
  refused on that ground: if its header is still compatible it can still be
  mapped and imported.
- **Filenames carry the identity for a person** and are trusted for nothing.

**Why the fingerprint is not the version.** Only the product knows whether a
change is meaningful. A fingerprint that flagged every change would flag an
added optional column, and a customer with a month-old template would be told
it was stale when it was fine. A version alone would miss a product engineer
who changed a field and forgot the bump. Both, each doing the job the other
cannot, is the smallest arrangement that answers all three questions above.

**The eleven other decisions, resolved 2026-09-29.** Each was put to the
owner in the analysis with a recommendation; the owner's direction is what is
recorded here, and where it matches the recommendation the reason is in the
analysis and not repeated.

| # | Decision | Resolution |
|---|---|---|
| D1 | A commit that completes with errors | **Refused.** The commit stays atomic; validation errors belong before it. "Completed with errors" is the dry run's `validation_failed`. Phase 2's acceptance criterion stands |
| D2 | Progress counts during a commit | **Not built.** Lifecycle stages and counts before and after are shown; nothing may imply a row is committed before the transaction is |
| D3 | A manual-review duplicate strategy | **Deferred.** Reject, skip and update are the three the engine offers, through `create`, `skip_duplicate` and `update` or `upsert` with a matcher |
| D4 | JSON as a template and source format | **Deferred.** No organisation default and no snapshot is touched to introduce it; the format enum, the table constraint and the reader seam keep the vocabulary so it can be added without redesign |
| D5 | Worker-written audit rows for validation and commit outcomes | **Accepted**, with a boundary: the run row stays the authoritative execution state and result; audit rows are immutable evidence of the moment, carrying counts and identifiers and never row content. This supersedes the Phase 2 position recorded in `docs/features/STATUS.md` under IMPORT-US-016, taken when the worker could not reach the audit sink without the API's configuration; IMPORT-DEF-008 removed that obstacle on 2026-09-20 |
| D6 | Template versioning | **This record** |
| D7 | A download-menu primitive | **Accepted.** One control, a disclosure over plain anchors, from the shell's own pattern |
| D8 | Example and help text as plain text in one language on the declaration | **Accepted**, with the trigger to revisit recorded in the analysis: a Python message catalogue for product keys |
| D9 | A read-only matcher on the target | **Accepted**, with conditions: tenant-scoped on the caller's session, no mutation, the product's own identity semantics rather than a second matching implementation, one call per run rather than one per row, and the commit remains authoritative — a prediction is a prediction |
| D10 | The error report as an annotated source file for re-import | **Deferred.** The browser-built problems file stays, with a consequence column |
| D11 | Per-row outcomes from the writer | **Deferred.** Counts only; the writer contract is unchanged |
| D12 | The decompressed-size ceiling for a workbook | **256 MiB**, summed from the zip directory before any sheet is opened, above the 64 MiB compressed ceiling that already bounds the source |

**Consequences.** `FieldSpec` gains `example` and `help`; `ImportTarget` gains
`version` and `matcher`; every existing declaration constructs unchanged. The
run records its format, the template version the file carried, the job id of
its last enqueue, the in-file duplicate count, the predicted counts and the
written counts, all nullable where a run from before this decision cannot
know them. XLSX joins CSV as a read format, and the three typed-value findings
carried from the Phase 2 review — IMP2-18, IMP2-19 and IMP2-21 — close with
it, because a workbook cell arrives typed and the engine has to normalise it
before the validator sees it. The audit registry gains four actions. JSON,
manual review, an annotated error file and per-row outcomes are each a
question with a recorded answer rather than an omission.
