# Templates, XLSX and the preview counts — verification run, 2026-09-29

What ran, against what, and what each answered. Every command here was
executed on 2026-09-29 against products generated into a scratchpad from the
working tree at `2fe5701` plus the uncommitted change; nothing in this file is
inferred from reading source.

## The estate

- `probe-import`: `pnpm create-koras-app probe-import --profile product
  --no-interactive --skip-registration --with data_import`.
- `probe`: the same without `--with`, so the default product.
- PostgreSQL 17.11, a private cluster initialised with initdb from the local
  PostgreSQL 17 binaries and started with pg_ctl on port 15434, because the
  Docker engine on this machine did not answer that afternoon. CI uses
  `pgvector/pgvector:pg16`; the difference is the major version and the
  absence of `pgvector`, which only `00010_ai_knowledge.sql` needs and which a
  product generated without `ai` does not carry.
- A real browser: Playwright's Chromium, with the identity provider, the API
  and the web application the product's own `playwright.config.ts` starts when
  `E2E_DATABASE_URL` is set, and the fixture target installed as
  `Generator Integration` installs it.

## Python

```
uv run ruff check python-packages services tests      All checks passed!   (both products)
uv run mypy python-packages services                   probe-import: no issues in 157 files
                                                       probe:        no issues in 136 files
uv run pytest tests/unit python-packages -q --no-cov   probe-import: 753 passed, 2 skipped
                                                       probe:        586 passed, 2 skipped
```

Of the 753: `python-packages/koras-import/tests` 116 (49 before this work,
67 added: `test_templates.py` 17, `test_xlsx.py` 18, `test_matching.py` 6,
and 4 more in `test_import.py`), `tests/unit/test_imports.py` 33 (19 before,
14 added), `tests/unit/test_import_templates_api.py` 7 (new, drives the
route through `TestClient`).

## Generator and documentation

```
generators/create-koras-app: npx vitest run tests/product-import.test.ts   52 passed
tests/docs:                  npx vitest run                                 490 passed
```

## Node

```
pnpm turbo run lint typecheck test build     Tasks: 71 successful, 71 total   (probe-import)
```

## PostgreSQL

On `koras_rls`, exactly as `generator-integration.yml` does it:

```
for file in supabase/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -q -f "$file"; done
   30 migrations applied, 00001 through 00038, no error
create role koras_rls_test nologin nobypassrls; grant ...
for file in supabase/tests/*.sql; do psql -v ON_ERROR_STOP=1 -v app_role=koras_rls_test -q -f "$file"; done
   23 suites, every one exit 0
   320_imports_isolation.sql: "one organisation one history: ok",
                              "no tenant fails closed: ok",
                              "the database keeps the two-actor rule: ok"
```

The suite includes the case this work added: the figures `00038` carries are
written on the tenant's own run, refused on another tenant's (row count 0),
and half a written record is refused by `import_runs_written_counts_together`.

The removed-force mutation check: every `force row level security` dropped,
`010_rls_structure.sql` rerun, exit non-zero. The suite refuses a schema whose
owner bypasses its policies.

Columns on `import_runs` after `00038`, read from the information schema:
`job_id`, `predicted_create`, `rows_created`, `template_version` nullable;
`rows_duplicate` not null.

On `koras_e2e`, the same 30 migrations, then `e2e/support/seed.sql`, then the
fixture run from `.github/fixtures/import-run.sql`:

```
E2E_DATABASE_URL=postgresql+asyncpg://koras_e2e_app:koras_e2e_app@127.0.0.1:15434/koras_e2e \
  uv run pytest tests/integration/test_import_commit_rls.py -q --no-cov
   4 passed
```

That is the commit path against a real database with a role that has no
`BYPASSRLS`, run with the product's own empty target list, before the fixture
was installed for the browser.

## IMPORT-DEF-010

`uv lock` on a copy of `probe-import` with the six declarations reverted to
`sqlalchemy>=2.0.0`, then the two lock files compared by package name and
version:

```
only after:  ['greenlet']
only before: []
version changes: []
sqlalchemy 2.1.1   greenlet 3.5.6
```

The extra adds one package and changes no other resolution. In the product's
environment `from sqlalchemy.ext.asyncio import create_async_engine` imports;
without the extra the same line raised `ModuleNotFoundError: greenlet`, which
is how the defect was found.

## Browser

The product's own `playwright.config.ts`, with `E2E_DATABASE_URL` set so it
starts the identity provider, the API and the web application, and
`E2E_IMPORT_FIXTURE=1` with the fixture target installed, exactly as
`Generator Integration` does:

```
E2E_DATABASE_URL=postgresql+asyncpg://koras_e2e_app:koras_e2e_app@127.0.0.1:15434/koras_e2e \
E2E_IMPORT_FIXTURE=1 CI=1 npx playwright test
```

**First full run: 161 passed, 1 failed, 9 skipped, 3.8 minutes.** The nine
skips are the pre-existing viewport-conditional cases in `shell.spec.ts` and
`live/`, unrelated to imports. The failure was the new template-menu case,
and it was two real defects rather than a test problem:

- Opening the panel moved focus to the *CSV* item, because the menu listed
  the target's formats in declaration order and the fixture declares CSV
  first. The brief and the case put Excel first. The panel now orders Excel
  then CSV whatever the declaration says.
- After a download the panel stayed open, so the next press on the button
  closed it and the second item could not be reached. Choosing an item now
  closes the panel and returns focus to the button.

Both fixed, the web application rebuilt, and the round-trip imports suite
rerun on its own:

```
npx playwright test --project=roundtrip e2e/roundtrip/imports.spec.ts    6 passed (34.4s)
```

That is the four cases from 2026-09-22 and the two new ones: the control
renders, Enter opens it with focus on the Excel item, Escape closes it with
focus back on the button, both anchors point at the route handler, the CSV
download is `fixture-contacts-template-v2.csv` holding a byte-order mark and
`email,name,kind` and nothing else, the Excel download is
`fixture-contacts-template-v2.xlsx`, a zip carrying `docProps/custom.xml`;
and the start card names the byte ceiling, the row ceiling and both formats,
with the file input accepting `.xlsx`.

**Manual case 53 was then executed in that browser at 375 pixels** with a
throwaway spec (not kept; `case53-375.png` beside this file is its
screenshot). It found a third defect: with a target rendered the page
scrolled sideways, before the menu was opened, to 497 pixels on a 375-pixel
viewport. The frame suite checks this width with no target, so nothing had
ever measured the page with the panel drawn. The cause is the history
table's screen-reader-only heading, absolutely positioned by `sr-only`
inside a scroll wrapper that was not positioned, so it escaped the clipping.
The three wrappers are `relative` now; the case reran clean, and it is a
permanent round-trip case from this day.

**Final full run, after all three fixes and with the new phone-width case in
the suite: 163 passed, 0 failed, 9 skipped, 3.2 minutes.** Same command as
the first run. The nine skips are the same nine.

## Not executed

Manual cases 44 to 52 need an upload -- a storage bucket, a queue and a
worker -- and a spreadsheet application. The round-trip harness is
deliberately bare of all three, and this machine has no Excel. They stay
blank in `../../manual/manual-test-results.md`, with the reason.
