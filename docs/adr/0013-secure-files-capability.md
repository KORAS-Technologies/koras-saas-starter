# ADR 0013 — `secure_files`: one coherent capability for trusted file bytes

**Status.** Accepted, 2026-10-06, ratified by the owner (the five decisions below).
Resolves the "release default" and "upload checksum contract" questions that
stopped the Docoris reconciliation of 2026-10-06.

**Context.** Docoris proved, over OD-10 / OD-12 / GR-367 / GR-373 / GR-369 / GR-374,
a chain by which a stored file's bytes are exposed only after they were
independently hashed, scanned and structurally assessed:

```
upload SHA-256 claim → incoming object → immutable finalization
 → digest/provenance verification → scanner → structural/integrity gates
 → clean verdict → canonical clean-only release
 → download / AI / OCR / retrieval / import enforcement
```

The Starter owned only fragments of that (the clamd service, `file_scan.py`
withholding, the import engine). Two things stopped the backport: a strict
clean-only release would leave every scanner-less product unable to serve files,
and a required `checksum_sha256` on upload-ticket issuance breaks the public
Files API for products that never asked for it.

**Decision.**

1. **A single capability, `secure_files`**, in the existing mechanism: a
   `capabilities:` entry in `profiles/product/manifest.yaml`, a `template_map`
   entry, a `defaults.yaml` entry, `requires:`, and the `--with/--without`
   flags. No second feature-flag system and no runtime toggle for the invariants.
2. **Disabled (the default):** a generated product behaves as it did — legacy
   `withheld()` release, today's upload-ticket contract, no scanner schema, no
   finalizer, no scanner service. Nothing is retrofitted into existing products
   and nothing about an existing product's downloads changes because the Starter
   was upgraded.
3. **Enabled:** the whole chain is generated and active as one unit. `requires:`
   makes the generator refuse a configuration missing a mandatory dependency
   (`storage`, `tenancy`, `rls`, the `worker` and `clamd` services). At runtime,
   if a mandatory setting is absent or invalid the product **fails closed**: it
   refuses to start (API and worker) or, where startup cannot refuse, releases
   nothing. It never falls back to legacy release.
4. **One API model, one generated constant, and two idioms for what differs by mode.** The mode
   is the single constant `koras_api.core.secure_files.SECURE_FILES` (mirrored by the worker's
   `koras_worker.secure_files`), rendered from the capability at generation time and never from
   a deploy-time switch. The routes, the request and response models and the one release
   primitive (`core/file_release.py`) are the same in both modes: there are not two files
   routers. What differs is carried by one of two idioms, chosen by one rule.

   * **Render-time per-mode bodies** (`{{#if capability.secure_files}}` in the template): the
     default. Used wherever the two modes differ in a contract, a signature, an import, a model or
     the existence of an object: the files router, the restore task, the AI, knowledge and import
     modules, `core/file_scan.py`, the web Files and import panels. The render **without** the
     capability is the pre-existing legacy text, byte for byte (generator tests hold it by digest),
     and a product never carries the other mode's code, so every import in a render resolves in
     that render.
   * **The generated constant branched at run time** (`if SECURE_FILES:`): only where both bodies
     can import and run in both renders and the difference is one decision inside one function
     (the dispatch in `core/file_release.py`, `secure_files_enabled()`). This is what lets a test
     switch the constant to exercise both modes in one tree.

   The rule: if the difference changes a signature, an import, a model, a table or whether a file
   exists, render it; if it is one decision over objects that exist in both renders, branch on the
   constant. When in doubt, render, because that keeps the default render untouched and the
   secure code absent from products that did not ask for it.

   A path listed under several capabilities in `template_map` is generated only when **all** of
   them are selected (the generator excludes every path listed under any component that is off).
   That is how the restore and promotion files are gated by `secure_files` and the capability they
   build on together.
5. **Upload contract.** `checksum_sha256` is **required** at upload-ticket
   issuance when `secure_files` is on: canonical lowercase 64-hex, an immutable
   claim bound to the ticket and upload id; the server never invents it. When
   off the field is optional and never a trust anchor, and no existing caller
   breaks. First-party generated clients/UI of a secure product compute and send it.
6. **Invariants that cannot be selectively disabled once enabled** (no setting,
   flag or env var relaxes any of them): clean-only release; the scanner is
   mandatory (`FILE_SCAN_BACKEND` ≠ `none`, no `skipped` bypass, no
   trusted-source bypass); finalization hashes the incoming bytes and the final
   copy to the claim and requires provenance **equal to the expected upload
   identity** (not merely non-empty); the final key is server-written only;
   ETag, LastModified and provider checksums are never trust anchors; every
   downstream consumer (download, AI, OCR, retrieval, derived content, import
   source) reads bytes only through the release primitive; restore/replacement
   begins non-releasable and needs a fresh scan decision.
7. **Import activation (GR-369) and promotion tooling (GR-374)** become generic
   Starter facilities: `IMPORTS_ENABLED` default OFF, enforced in the API and the
   worker, declared per environment, absent-means-off, with drift checks.
   Product-specific wiring (Fly app names, Doppler configs, F1 dispositions,
   security-register entries) is configuration, never Starter code.
8. **Docoris consumes `secure_files = enabled`** and stays behaviourally
   equivalent to the proven OD-10/GR-373 implementation. The Starter
   generalizes; Docoris is not weakened to fit.
9. **Forged-provenance qualification regression.** The provider-qualification
   harness gains a disposable, test-only case in which a copy-source ticket is
   intentionally left unguarded and the copied provenance is forged and
   non-empty; finalization must still refuse because provenance ≠ the expected
   upload identity. No production guard is weakened to build it and no new
   invariant is introduced.

**Consequences.** `secure_files` is the recommended configuration for any product
that stores customer documents; the generator says so and the default stays off,
so existing generation output is byte-identical. The capability → artefact
mapping is maintained in `docs/SECURE_FILES.md`.
