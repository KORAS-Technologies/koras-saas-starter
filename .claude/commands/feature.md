# /feature

Implement the requested feature using the Koras engineering workflow.

Request:

```text
$ARGUMENTS
```

Instructions:

1. Read `.claude/CLAUDE.md` and the relevant Koras skills.
2. Search the repository for related implementations, reusable components, clients, schemas, services, tests, and docs.
3. Summarize acceptance criteria and affected architecture.
4. For non-trivial work, provide a concise implementation plan before making broad edits.
5. Implement the smallest coherent solution using existing patterns.
6. For React/Next.js work, apply installed React best-practices and frontend-design guidance where relevant.
7. Apply Koras UI, forms, auth, multitenancy, Supabase, security, and accessibility guidance as applicable.
8. Add/update tests.
9. Run lint, typecheck, tests, and build scripts that exist.
10. For user-facing changes, verify the critical path with Playwright, inspect console errors, and check desktop/mobile behavior.
11. Review `git diff` using `koras-code-review` before declaring completion.
12. Summarize files changed, behavior implemented, verification performed, and any remaining risks.

Do not mark the feature complete based only on successful compilation.
