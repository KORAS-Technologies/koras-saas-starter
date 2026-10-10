# Execution ledger — autonomous completion run

> Scope: the work items of the autonomous completion run opened on
> 2026-10-10, one row each, with the evidence that moves a row. It is a
> status record and decays like one: **check GitHub before trusting a row**
> (`gh pr view <n>`, `gh pr checks <n>`, `gh run list --branch develop`). A
> new session reads this file, then verifies every row it intends to act on.
>
> It does not restate entries that already live elsewhere. `docs/FOLLOW_UPS.md`
> owns what was left undone and why, `docs/RISK_REGISTER.md` owns risks, and
> `docs/features/local-zitadel-follow-ups/README.md` owns the Phase 4.3A
> follow-up plans. A row here points at those rather than describing them again.

## Standing constraints

These are the owner's instructions for this run, recorded on 2026-10-10.
They apply to every row and are not relaxed by any row.

- PR #63 is not merged without the owner's explicit approval.
- Stage 4.3B provisioning does not start. Readiness work that changes no
  credential, masterkey, issuer, identity volume or real instance is in scope.
- GitHub rulesets, repository visibility, credentials, Docker volumes and the
  TEST and PROD environments are not modified.
- The existing Control Plane and Lexveria ZITADEL instances on the Windows 10
  machine are not touched.
- No agent approves its own work as an independent reviewer.
- A merge happens only where the ruleset and the owner both allow it. The
  ruleset requires zero approvals as of 2026-10-10 (F32), so "the checks are
  green" is not authorisation.

## Baseline

Verified 2026-10-10:

- PR #71 merged at 17:50 UTC as `41a7c5d`, PR #72 at 17:55 UTC as `ccfc19d`.
- `develop` at `ccfc19d8c5067e9b605a62b6025b46b8aff57b3d`: CI, Security,
  Generator Integration and CodeQL green on the push.
- Required checks (ruleset 24385352, strict): Lint & Typecheck, Test (Python),
  Test (Node), Build, Secret scan (gitleaks), CodeQL (python),
  CodeQL (javascript-typescript), Generator Integration.
- `test`, `staging` and `main` have no ruleset and no branch protection, and
  there is no CODEOWNERS file, both as of 2026-10-10.
- Secret scanning is disabled on the repository as of 2026-10-10; gitleaks in
  CI is the only secret scan.

## Work items

| ID | Phase | Item | Risk | Owner | Branch / PR | Evidence | Status | Next action |
|----|-------|------|------|-------|-------------|----------|--------|-------------|
| B1 | B | Handlebars 4.7.9 → 4.7.10 for Dependabot #14, #15 (critical) and #16 (moderate) | Medium: a build-time dependency of the generator | dev: orchestrator; review: independent security and QA agents | `dependabot/npm_and_yarn/handlebars-4.7.10`, PR #63, head `afa5d050` | Lock diff is handlebars only; Dependabot's unrelated rollup bump dropped. Integrity matches the registry. `pnpm audit` clean. 761 rendered templates byte-identical under 4.7.9 and 4.7.10 across four capability sets. Security review: APPROVE WITH NOTES | Awaiting CI and QA as of 2026-10-10 | Owner's merge decision |
| B2 | B | CodeQL #5 polynomial ReDoS in `reporting_schedules.py`; #6 and #7 substring host match in `provider_qualification.py` | Low to medium: authenticated route; an evidence label | dev agent T2 | `fix/codeql-redos-url-host` | — | In progress as of 2026-10-10 | Independent review once the PR is open |
| C1 | C | Windows CRLF: no LF rule for `*.mjs`, `*.mjs.hbs`, `*.sh.hbs`, `Dockerfile.hbs`, `*.yml`; 12 generator tests and the `local-zitadel-secure` import fail on a CRLF checkout; the Windows CI job runs only `-t masterkey.mjs` | Medium: generated scripts can be CRLF on a Windows-generated product | dev agent T1 | `fix/windows-crlf-eol` | The 12 failures reproduce identically with handlebars 4.7.9 and 4.7.10, so they predate B1 | In progress as of 2026-10-10 | Independent review once the PR is open |
| D1 | D | Bind generated projects' published ports to loopback (F33) | Medium: a development database reachable from the LAN | dev agent T3 | `fix/local-ports-loopback` | — | In progress as of 2026-10-10 | Independent review once the PR is open |
| D2 | D | R-045: `minio/minio:latest` cannot be pulled; CI uses a stand-in | High (severity 15) | unassigned | — | — | Not started as of 2026-10-10 | Choose a pinned, pullable image: an owner decision if it changes the image vendor |
| D3 | D | R-046: the factory's root stack runs ZITADEL on the public placeholder key and default password | Medium (severity 8) | — | — | — | **Blocked on an owner decision** (retire or migrate), recorded 2026-10-10 | Owner decision; changing it alters an existing identity instance |
| A1 | A | F33 missing from the `FOLLOW_UPS.md` ordering table | Low | orchestrator | `docs/execution-ledger` | — | Done on the branch, 2026-10-10 | Merge with this ledger |
| A2 | A | CODEOWNERS, approval enforcement, and protection for `test`, `staging` and `main` | High: governance | — | — | — | **Blocked: owner-authorised settings change**, recorded 2026-10-10 | Prepare a proposal; do not apply |
| A3 | A | 113 local and 64 remote branches already merged into `develop`; a local `develop` 28 behind; two leftover worktrees from an earlier session | Low | — | — | Discovery pass, 2026-10-10 | Recorded, not acted on | Deleting branches needs the owner's instruction |
| A4 | A | An unmerged local branch numbers its entry F33, which is already taken on `develop` | Low | — | `docs/follow-up-refresh-modules-settings-local` | — | Recorded 2026-10-10 | Renumber when it is picked up |
| E1 | E | ADR 0018 instance retirement: Proposed, four owner questions open | High | — | — | — | **Decision required**, recorded 2026-10-10 | Owner answers the four questions in ADR 0018 |
| F1 | F | T-E4 real Doppler CLI, T-E5 Doppler access isolation, T-E6 independent offline restore | High | — | — | — | **Blocked**, recorded 2026-10-10: each needs real-environment evidence, namely Doppler authorisation, the owner's OpenPGP recovery key and an external volume | Owner provides the prerequisites; nothing here may be claimed without executing it |

## Local working tree

On 2026-10-10 the main checkout's two modified files,
`profiles/_shared/template/local/scripts/stack.mjs.hbs` and
`profiles/_shared/template/local/zitadel/credentials.mjs`, differed from
`HEAD` only in line endings (LF in the working tree, CRLF everywhere else).
They are left as they are; C1 is the change that makes the workaround
unnecessary.
