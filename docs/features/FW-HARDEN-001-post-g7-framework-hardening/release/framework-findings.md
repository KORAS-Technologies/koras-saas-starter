# FW-HARDEN-001 — framework findings

What this maintenance cycle found about the framework, 2026-09-21, beyond the
three findings it was sent to fix. Carried to
`docs/platform/gap-defect-register.md` rather than left here.

---

## FW-GAP-011 — the factory's own source is outside the classifier's domain

`generators/` and `tooling/` classify as nothing. Under the new fail-closed
rule that is a stop rather than a silent reuse, which is the safe direction,
but it is still a hole.

The question it raises is not an edit. The change classes are named for a
*product's* shape — `frontend_code`, `backend_code`, `e2e_test`. Whether the
factory's own production code belongs in that vocabulary, or whether the
factory needs a domain of its own, is a decision, and a maintenance cycle
authorised for two findings should not make it alone.

**Severity: Medium.** Asserted in the suite so that closing it later has to be
deliberate.

## FW-GAP-012 — `tests/**` classes a Node test as a Python test

`automated_test_python` owns `tests/**` and is reached before the Node
patterns. This repository has two Node workspaces under that path,
`tests/docs` and `tests/e2e`, both declared in `pnpm-workspace.yaml`. A change
to either invalidates the Python gates and reuses the Node ones — backwards,
though both are cheap and both usually run anyway.

Left because getting it right means deciding whether a browser suite living
under `tests/e2e` is `e2e_test` or `automated_test_node`, which is a judgement
rather than an edit. The matrix deliberately asserts no row that would bless
the current behaviour.

**Severity: Low.**

## FW-GAP-013 — nineteen template files the vocabulary has no class for

Found by measurement after the independent review showed the coverage
assertion could not fail. Three groups:

| Group | Files | What they are |
|-------|-------|---------------|
| The framework's own contract | 15 | `.claude/orchestration/*.yaml` and `.claude/domain/*.yaml` — including every file this cycle edited |
| Repository hygiene | 3 | `.gitattributes`, `.gitignore`, `.gitleaks.toml` |
| The platform contract | 1 | `contracts/product-platform.v1.json` |

Each would need a new change class, and a new class needs a gate that depends
on it — `gate-invalidation.yaml` asserts that no class exists which invalidates
nothing. That is a change to `quality-gates.yaml`, and out of scope here.

The third group is the interesting one: `contracts/product-platform.v1.json` is
the single edit in a product repository that another repository can observe,
and the vocabulary has no word for it.

**Severity: Medium.** Counted in the contract and asserted exactly, so the
number moves when anything does.

---

## Two observations about the framework, not defects in it

### A remedy creating the condition for the next defect, for the third time

G7 R2 recorded this twice: FW-GAP-007's fix exposed FW-GAP-009, and
FW-GAP-003's fix produced FW-GAP-010. This cycle did it again, and worse —
the fix for FW-GAP-010 **rebuilt FW-GAP-010** with `CLOSED` in place of
`final_acceptance`. The summary waited for closure and closure waited for the
summary.

Three occurrences is a pattern rather than bad luck, and the pattern has a
shape: each was a rule about *ordering* written in one file while the
constraint it interacted with lived in another. `telemetry.yaml` did not know
that `CLOSED` had a `requires` list; `lifecycle.yaml` did not know that
reaching CLOSED was an event kind.

What caught it was an independent review of the fix. What did **not** catch it
was the fix's own test group, which asserted that the contract contained
certain strings — all of which it did. **A contract test that reads the
contract's words cannot find a contradiction between two contracts.** The
ordering is now asserted as an ordering, which is the smallest change that
would have caught it.

### The suite that validates the framework had never matched a path

FW-GAP-006's real shape is narrower and more interesting than "the globs are
wrong". The globs had never been *executed*. Every assertion about change
classes started from a class name already given — `change_classes:
[frontend_code]`, what does that invalidate — so the half of the contract that
decides which class a path gets had no test at all, in a file that otherwise
tests the framework exhaustively.

It is the same shape as the G7 R2 review's own observation about the two seams
it examined: every assertion asked what was decided, and none asked what it
cost or whether it took effect. Here, every assertion asked what a class
implies, and none asked whether a path reaches one.

---

## What this cycle did not find

- **No wrong rule**, again. As in G7 R1 and R2, every finding is a question the
  contract had not written down or a reach that did not match an intent.
- **The risk model classified correctly.** STANDARD was right: the review found
  no security, tenancy or data concern, which is what "no floor signal fired"
  predicted. It found plenty else.
- **Capability routing held.** 11 of 40 agents activated; the 29 excluded would
  each have found nothing, and the review — asked to contradict that — agreed.
- **The freeze points held.** Code freeze was declared at `575acaf`, and
  everything after it is remediation of blocking findings, which is what the
  freeze permits.
