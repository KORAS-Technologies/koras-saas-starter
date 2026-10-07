"""Promotion readiness for a product generated with `secure_files` (ADR 0013 sections 7 and 9).

Read-only checks that decide whether an environment may be *asked* to activate data import and
to rely on the secure-files chain. Nothing here enables anything, writes to a database or a
secret store, or prints a secret, an object key or a file name. A check that cannot establish its
answer FAILS: unknown is never a pass.

What is generic (this package) and what is the product's (`local/config/promotion.yaml`,
`local/config/f1-dispositions.yaml`, the security register) is documented in `docs/SECURE_FILES.md`,
"Promotion tooling".

    PYTHONPATH=tooling uv run python -m promotion <gate|activation|f1|provider|config> ...
"""
