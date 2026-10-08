# Data import — manual test plan

Written 2026-09-19, against Phase 1 as built; the commit cases added
2026-09-20. **Ten of the forty are covered as of 2026-09-22: eight executed by
hand — 23, 24, 25, 26, 36, 36b, 37 and 39, all PASS — and 17 and 28 by
`e2e/roundtrip/imports.spec.ts`, which `Generator Integration` runs against a
fixture target.** The two are counted separately: a case a person walked through
and a case a suite asserts are different kinds of evidence. The verdicts and the estate are in
`testing/manual/manual-test-results.md`; the columns below are left blank
rather than filled in two places.

These are the cases no automated test in this estate reaches. The e2e harness
starts the web application alone, so its four browser checks cover routing,
refusal and degraded rendering and nothing that needs an API, a queue or a
bucket. The unit and isolation suites reach the store and the tables but never
a file a person actually chose.

Each case needs: a deployed product generated `--with data_import`, a declared
import target (the generated product declares none — this needs a repository
that does, or a target added by hand), Redis configured, a storage bucket
configured, and an account holding `imports.manage`.

| # | Case | Expected | Verdict |
|---|------|----------|---------|
| 1 | Upload a clean CSV of 20 rows whose headings match the target exactly | Every column is pre-mapped; the preview shows the first row's values | |
| 2 | Press *Check the file* on that mapping | The run moves to *Checking the file…*, then to *Ready for review* without a page reload | |
| 3 | After case 2, count rows in the target table | Unchanged. This is the property the whole phase exists for | |
| 4 | Upload a CSV with one heading the target does not know | That column defaults to *Do not import*; the rest are mapped | |
| 5 | Map a column to a field, then map a second column to the same field | The save is refused with a 422 naming the field, in the reader's language | |
| 6 | Leave a required field unmapped and press *Check the file* | Refused at mapping time, naming the field — not after a validation run | |
| 7 | Upload a CSV with an empty required cell and a malformed email in the same row | The report lists **both** problems for that row, not the first only | |
| 8 | Upload a CSV saved from Excel as "CSV (Windows)" with an accented name | The name renders correctly, or the *characters were replaced* banner appears. Never a silent mojibake | |
| 9 | Upload a semicolon-delimited CSV (a German Excel export) | The delimiter is detected; columns are not one giant column | |
| 10 | Upload a file one row over the target's `max_rows` | Refused with the too-many-rows sentence. The file is **not** truncated | |
| 11 | Upload a file larger than `files.maxUploadSizeMb` | Refused at the ticket, before any bytes are sent | |
| 12 | Upload a `.exe` renamed to `.csv` | Refused by `files.allowedExtensions` at the ticket, or parsed and rejected — never written | |
| 13 | Start a run against a file whose scan status is `pending` | Refused, with a sentence distinguishable from "the file is gone" | |
| 14 | Stop the worker, then press *Check the file* | The run stays visible in *Checking the file…* rather than vanishing. It is findable afterwards | |
| 15 | Unset `REDIS_URL` on the API, then press *Check the file* | 503 with the queue-unavailable sentence. The run is **not** moved to `validating` | |
| 16 | Press *Discard this import* on a mapped run | The run becomes *Cancelled* and disappears from the working area but stays in the history | |
| 17 | Sign in as a member without `imports.manage` and open `/dashboard/imports` | The module is absent from the sidebar, and the typed URL is refused | |
| 18 | As tenant A, take a run id from tenant B and open `/api/v1/imports/<id>` | 404, not 403 — the row is not visible, so there is nothing to forbid | |
| 19 | Switch the interface to German and repeat case 7 | Every state, every problem code and every refusal is in German. No bare identifiers | |
| 20 | Open the page at 375px and run cases 1 and 2 | Nothing scrolls sideways; the mapping table scrolls inside its own container | |
| 21 | Open the page with the API stopped | The error banner, and **no** picker. Never "this product does not accept any imports yet" | |
| 22 | Check the browser console throughout | No hydration warnings, no uncaught errors | |

## Phase 2 — the commit

Added 2026-09-20. These need a product that declares a **committable** target,
which a generated product does not — so 23 to 26 were run on 2026-09-22 against
a generated product given the smallest possible one: a `probe.contacts` target
with a real writer and a tenant-scoped table, both of which live in
`testing/runs/2026-09-22-01/` and neither of which is part of the starter.

**Cases 23, 24, 25, 26, 36, 37 and 39 PASS.** Case 26 is the phase's own
acceptance criterion and it was made to fail the hard way: the writer writes two
of three rows and *then* raises. Case 36 covers the route's paging contract and
not the browser's download, which is NOT EXECUTED. The other twelve are NOT
EXECUTED.

| # | Case | Expected | Verdict |
|---|------|----------|---------|
| 23 | Check a clean 20-row file, then press *Import these records* | The run moves to *Confirming…* then *Imported*, and says how many were written | |
| 24 | After case 23, count rows in the target table | Exactly 20 more, each carrying the run id if the target attributes to the run | |
| 25 | Press the confirm control twice quickly | The second is refused with a 409. **One** copy of the records exists | |
| 26 | Make the writer raise on row 15 of 20, then confirm | The run is *Failed* with a sentence, and the target table has **zero** new rows. This is the criterion the phase exists for | |
| 27 | Make the writer raise, and check the audit log afterwards | `import.run.committed` is there for the confirmation, **and since 2026-09-29** `import.run.finished` with outcome `error` and the run's own sentence (ADR 0012 D5). This row said "not a fourth audit action" until that day | |
| 28 | Confirm a run against a target whose writer was removed | No confirm control renders at all; a POST to the route answers `import_not_committable` | |
| 29 | Kill the worker mid-commit, then look at the run | It stays in *Confirming…*. The target table has zero new rows. It is findable | |
| 30 | Unset `REDIS_URL` on the API, then confirm | 503 with the queue sentence, **and** the run is marked failed rather than left looking confirmed | |
| 31 | After a successful commit, open the bell | A notice saying the import finished, in the recipient's own language, linking to `/dashboard/imports` | |
| 32 | Switch `notifications.inAppEnabled` off for that member and repeat case 31 | No notice. Nothing else changes | |
| 33 | After case 31, check the mail inbox | **Nothing.** The notice is in-app only, and this case exists so that stays deliberate | |
| 34 | Import a file whose rows duplicate existing records, with *skip duplicates* | The counts distinguish created from skipped, and they sum to the file's rows | |
| 35 | Repeat case 34 with *update matching* | The counts show updates, and no duplicate records exist | |
| 36 | Make a file with 12 bad rows, check it, press *Download every problem* | A CSV opens in a spreadsheet with 12 rows plus a header; the row numbers match the source file's left margin | |
| 37 | Put a comma, a quote and a newline into a bad cell, then do case 36 | The spreadsheet shows one row, not three, with the cell intact | |
| 38 | Change a target's field rules, then confirm a run checked before the change | Refused, naming that the rows no longer pass. Nothing is written | |
| 39 | Sign in as a member without the target's own permission and POST the commit route | 403, and `import.run.refused` is recorded | |
| 40 | Switch to German and repeat cases 23, 26 and 36 | Every state, sentence and column heading in German. No bare identifiers | |

## What a pass would not prove

Cases 1–22 exercise Phase 1 and write nothing. Cases 23–40 exercise the commit.
Neither set reaches XLSX or JSON, saved mapping profiles, cancelling a commit in
flight, or a file at the row ceiling under real latency — those are Phases 3
and 4.

## Templates and formats

Added 2026-09-29, with the template, the XLSX reader and the preview counts.
None has been executed. Each needs the estate the cases above need, and a
spreadsheet application.

| # | Case | Expected | Verdict |
|---|------|----------|---------|
| 41 | Open the Imports page and activate *Download template* with the keyboard | Enter opens the panel with one item per format the target accepts and focus on the first; Escape closes it and returns focus to the button | |
| 42 | Download the Excel template and open it in Excel | A *Data* sheet with the field names in row 1, required ones shaded, a comment on each heading; an *Instructions* sheet naming target, version, fingerprint and every field | |
| 43 | In the Excel template, type a value outside an enumerated column's list | Excel refuses it with the sheet's own message | |
| 44 | Fill ten rows in the Excel template, save, upload | The mapping card says every column matches and nothing needs mapping by hand; the sheet named is *Data* | |
| 45 | Check the file from case 44 | The preview shows total, ready, with problems and duplicated; the predicted figures when the target declares a matcher, or the sentence saying they are unknown | |
| 46 | Save the same rows from Excel as CSV and upload that | The same verdict and the same figures as case 45 | |
| 47 | Download a template, then have the product bump the target's version, then upload the old template filled in | The mapping card says the file was made from an older template and names both versions; the run still proceeds if the header fits | |
| 48 | Rename a heading in a downloaded template and upload it | The verdict names the column as unknown and, if required, the field as missing | |
| 49 | Upload an `.xlsm` renamed to `.xlsx` | Refused as a workbook with macros, before any sheet is read | |
| 50 | Confirm an import against a target with a writer | The card draws total, created, updated, skipped and failed, and the history row keeps the format | |
| 51 | After case 50, read the audit page | `import.template.downloaded`, `import.run.validated` and `import.run.finished` are there under the right actor, with counts and no cell values | |
| 52 | Under `create`, upload a file naming a record that exists, on a target with a matcher | The row is listed with the already-exists sentence and the run does not reach `validated` | |
| 53 | Open the page at 375 pixels and repeat case 41 | The panel opens below the button at full width; nothing scrolls sideways | |
