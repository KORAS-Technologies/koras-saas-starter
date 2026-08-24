# /review

Review the current working-tree diff or the specified scope.

Scope/request:

```text
$ARGUMENTS
```

Instructions:

1. Read `.claude/CLAUDE.md` and `koras-code-review`.
2. Inspect `git status` and the relevant diff unless another scope is explicitly supplied.
3. Review correctness, architecture, React/Next.js patterns, type safety, auth, permissions, tenant isolation, security, accessibility, performance, UX states, tests, observability, and unrelated changes.
4. Classify findings as CRITICAL, HIGH, MEDIUM, or LOW.
5. For each finding provide location, impact, and a concrete fix.
6. Do not create speculative findings merely to populate categories.
7. If no blocking issues are found, state remaining verification or coverage gaps.
8. Do not approve with unresolved CRITICAL or HIGH findings.
