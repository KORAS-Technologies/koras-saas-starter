# Local ZITADEL: follow-ups to Phase 4.3A

**Status as of 2026-10-10: Planned. Only the loopback plan has started.** These are plans, not
work. Each was identified while reviewing PR #66 (Phase 4.3A, secure local
ZITADEL), and each was deliberately left out of that PR so its validated head
stayed unchanged. Nothing here is approved for implementation until the owner
says so. Where a plan names an owner decision, that decision comes first.

| Plan | What it closes | Owner decision first? | Before Stage 4.3B? |
|------|----------------|-----------------------|--------------------|
| [`adr-0018-instance-retirement.md`](adr-0018-instance-retirement.md) | The open item in ADR 0015: no way to retire an escrowed instance or escrow a second one | Yes: approve ADR 0018, plus four questions | **Yes.** No escrow record exists as of 2026-10-10, so renaming costs no migration |
| [`r045-minio-image.md`](r045-minio-image.md) | R-045: `minio/minio:latest` cannot be pulled; CI uses a stand-in | Yes: which image | No, but `make dev` is broken on fresh machines until it lands |
| [`r046-factory-identity.md`](r046-factory-identity.md) | R-046: the factory's own stack runs ZITADEL on the placeholder key and default password | Yes: retire or migrate | No |
| [`loopback-local-services.md`](loopback-local-services.md) | Security review, Medium: the database behind ZITADEL is published on every interface. Steps 1 to 3 built on 2026-10-10 (generated projects only); step 4, the CI socket check, is left | No | Recommended |
| [`crlf-and-review-notes.md`](crlf-and-review-notes.md) | The CRLF test-import failure, and the remaining security and QA review notes | No | Items 1 to 4 of its table: yes |

**Independent of all of these:** manual cases T-E4 (the real Doppler CLI's
behaviour), T-E5 (Doppler access scope) and T-E6 (an independent restore)
remain mandatory before any real instance is provisioned. No plan here
replaces them.

Sources: ADRs 0015 to 0018, R-045 and R-046 in `docs/RISK_REGISTER.md`, and
the PR #66 security and QA reviews of 2026-10-10.
