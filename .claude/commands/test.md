# /test

Verify the requested feature or current working tree without making unrelated changes.

Target:

```text
$ARGUMENTS
```

Instructions:

1. Read `.claude/CLAUDE.md` and `koras-testing`.
2. Identify the repository-standard verification commands.
3. Run applicable lint, typecheck, unit/integration tests, and build.
4. For user-facing features, start the required local services and run the critical flow with Playwright.
5. Check browser console errors and at least one desktop and one mobile viewport.
6. Test applicable failure paths, validation, unauthorized/forbidden behavior, and tenant isolation.
7. Avoid arbitrary sleeps in browser tests; wait on explicit conditions.
8. Report exactly what passed, failed, or could not be executed.
9. If a failure is caused by the implementation and the requested scope allows fixes, fix it and rerun the relevant checks.
