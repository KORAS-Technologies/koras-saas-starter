# G7R2-F01 - QA evidence audit

**Not yet executed, as of 2026-09-21, 17:40Z.** `qa-reviewer` writes this after the
manual pass, and it is independent: the agent that produced the evidence does not
audit it.

What it will answer, per `quality-gates.yaml` `qa_evidence_audit` and
`documentation-policy.yaml` `evidence_rules`: whether every manual case carries all
the required fields, whether every verdict is one of PASS, FAIL or BLOCKED, whether
every screenshot is a genuine capture from an executed step at the canonical path,
whether each capture's purpose is stated where it is not obvious, and whether the
primary evidence supports the claim made about it and no more.
