# Data import — manual test plan

Written 2026-09-19, against Phase 1 as built. **Every verdict below is blank.
No manual pass has been run.**

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
| 2 | Press *Check the file* on that mapping | The run moves to *Checking the file…*, then to *Checked. Nothing was written.* without a page reload | |
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

## What a pass would not prove

Cases 1–22 exercise Phase 1 only. None of them writes a row, because nothing in
Phase 1 can. The commit, its atomicity, its idempotency and the error file are
Phase 2 and have no cases here yet.
