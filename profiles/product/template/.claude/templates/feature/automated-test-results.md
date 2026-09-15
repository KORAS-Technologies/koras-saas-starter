# <FEATURE-ID> — Automated Test Results

**Build / commit:** <sha>
**Environment:** <name>
**Run date:** <YYYY-MM-DD>
**Executed by:** <agent or person>

## Results

| Suite | Command | Passed | Failed | Skipped | Outcome |
|-------|---------|--------|--------|---------|---------|
| Lint | `pnpm lint` | | | | |
| Typecheck | `pnpm typecheck` | | | | |
| Unit | `pnpm test` | | | | |
| Integration | | | | | |
| E2E | | | | | |

Record actual executed results. A suite that was not run is recorded as
**not run**, never as passed.

## Failures

| Suite | Test | Failure | Routed to |
|-------|------|---------|-----------|

## Skipped tests

| Test | Reason | Who will unskip it |
|------|--------|--------------------|
