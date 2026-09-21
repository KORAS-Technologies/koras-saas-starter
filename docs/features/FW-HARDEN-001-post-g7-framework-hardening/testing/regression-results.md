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

**Reordering `frontend_code` above `backend_code`.** A class order change can
silently move files between classes. Measured: the old vocabulary against the
new, over every tracked path in all three template trees — **the class of
exactly zero real files changed**. Every stylesheet in the estate already
classified as `frontend_code` by directory. The reorder and the stylesheet
globs are written for the file somebody adds next, and cost nothing today.

**Widening `deployment_config` to `local/**` and the build graph.** This one
*does* move files: 25 that previously classified as nothing now classify as
`deployment_config`. That is the intended effect, and the direction is
conservative — they move from "no gate invalidated" to "the deployment gates
invalidated", never the reverse. Nothing moved out of another class, because
nothing else matched them.

**Adding `pnpm-workspace.yaml` to `dependency`.** One file, previously
unclassified.

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
