# FW-HARDEN-001 — regression results

Required by `cross_feature_or_release`: a shared contract changed, so the
question is not only "does the new thing work" but "does everything that reads
the old thing still hold".

Executed 2026-09-21, after the remediation of the independent review's findings.

---

## What reads the contract, and what happened to it

| Reader | How it is verified | Result |
|--------|--------------------|--------|
| `orchestration.test.ts` — the whole framework contract | 557 assertions over every orchestration file, the 40 agent definitions, the registry, the activation rules, the workflow and both profile trees | **pass** |
| The gate scenarios | Six declared scenarios, each deriving invalidation and reuse from the gates' own `inputs` rather than a hand-written table | **pass, unchanged** |
| The applicability vocabulary | Every condition id in `activation-rules.yaml`, `quality-gates.yaml` and `documentation-policy.yaml` resolved against `conditions.yaml` | **pass, unchanged** |
| Profile isolation | The Control Plane must not receive the product orchestration contract | **pass, unchanged** |
| Template parity | No path may exist in both profile templates with identical content | **pass, unchanged** |
| Generation | A product and a Control Plane built from the templates | **pass** |
| Documentation gates | Paths, identifiers, lists and hedges across every `.md` under `docs/` | **pass** — 424 |
| Python | ruff, mypy, pytest | **pass** |

## The regression this change could plausibly have caused

Three, and each was checked directly rather than covered by "the suite is
green".

The measurement is **class movement**: every distinct path a product receives,
classified under the baseline vocabulary and under this one, and compared. 807
paths.

| Movement | Paths |
|----------|-------|
| nothing → `frontend_code` | 276 |
| nothing → `backend_code` | 179 |
| nothing → `deployment_config` | 38 |
| nothing → `dependency` | 44 |
| nothing → `e2e_test` | 22 |
| nothing → other | 13 |
| **between two real classes** | **0** |
| **files that lost a gate** | **0** |

Every movement is from unclassified to classified, which is strictly more
invalidation. That is the property that matters, and it is the one the first
version of this document asserted without measuring.

**It was not true when first written, and final acceptance caught it.** The
build-graph globs were written with a leading globstar, so
`**/tsconfig*.json` reached every application's and package's own tsconfig —
26 files that had classified as `frontend_code` (16 gates) and now classified
as `deployment_config` (5). An edit to `packages/ui/tsconfig.json`, which can
change how every frontend file compiles, would have reused the test, browser,
accessibility and independent-review gates. This document said in as many
words that nothing moved out of another class. It had.

That is FW-GAP-006's own failure mode produced by FW-GAP-006's fix, and the
third time in this one cycle that a remedy created the next defect. The globs
are anchored at the root now, and the gap that hid it is closed: the coverage
assertion counts paths that classify as *nothing*, so a path moving between
two real classes was invisible to it. The new invariant — nothing inside an
application is `deployment_config` unless it is literally a deployment
descriptor — is what covers that family.

**The stylesheet rule and the class reorder still change nothing today.** Every
stylesheet in the estate already classified as `frontend_code` by directory.
They are written for the file somebody adds next, and that is recorded as
costing nothing rather than presented as a fix.

## What was not re-run, and why

| Not run | Why |
|---------|-----|
| Browser suite against a live API | Requires `E2E_DATABASE_URL` and four servers. Nothing in this change renders, and `user_interface` is not met. The browser suite that does run — the generated product's, inside Generator Integration — is a remote gate and is listed for the push. |
| Live infrastructure | No Terraform, no provider, no estate. |
| Downstream product repositories | No generated application byte changes. Verified, not assumed — see the release notes. |

## Convergence

No concurrent work. The tree was clean at 7199f85 at the start, the branch is
the only one touching these files, and the two pre-existing worktrees on this
machine are unrelated and were left alone.
