# Run 2026-09-21-09 - the accepted tree's own suite

| | |
|---|---|
| **Gate** | `automated_tests_pass`, re-established after the post-audit corrections |
| **Commit under test** | `dc4a946` — the documentation corrections, plus two `MOVED` entries in `tests/docs/file-references.test.ts` |
| **Why it exists** | `dc4a946` changed a file of class `automated_test_node`. Under the code-freeze rule that edit invalidates no gate, but the docs suite grew from 400 checks to 409 with this feature's own evidence in it, and the frozen commit's green run was taken against the 400. A number quoted for one tree and evidenced on another is the R-042 shape. |
| **Command** | `pnpm test`, from the worktree root |
| **Result** | **PASS** |

```
create-koras-app  61 files, 2191 passed
koras-docs-tests   5 files,  409 passed
koras-cli          7 files,  120 passed
koras-e2e          2 files,   21 passed, 2 skipped
pytest                         7 passed
Tasks: 5 successful, 5 total     EXIT=0
```

Full capture: `pnpm-test-after-doc-corrections.txt`.

**Committed rather than left in the working directory.** `final-acceptance` withheld
READY partly because this run existed only on disk: the accepted commit carried no
committed evidence that its own suite passed, and an untracked run directory is not a
retained one.

## What it does not establish

That CI will agree. This is one machine, and `quality-gates.yaml` is explicit that a
post-merge gate is never satisfied by a local result however identical the command was.
`ci_verified` is where the pushed commit is judged.
