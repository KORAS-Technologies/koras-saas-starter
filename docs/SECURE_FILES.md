# Secure files

> Scope: the `secure_files` capability ([ADR 0013](adr/0013-secure-files-capability.md)).
> This page is the capability's contract and its artefact map. It makes no claim
> about whether any workflow is passing; check the commit you are on.

## Purpose

A stored file's bytes are exposed only after they were independently hashed,
scanned and structurally assessed, and then released clean-only:

```
upload SHA-256 claim -> incoming object -> immutable finalization
 -> digest/provenance verification -> scanner -> structural/integrity gates
 -> clean verdict -> canonical clean-only release
 -> download / AI / OCR / retrieval / import enforcement
```

The behaviour was proven in Docoris (OD-10, OD-12, GR-373) and is generalized
here layer by layer. **Layer 1 (this change) is the scaffold only**: the
capability, its generation switches, the generated constant and the fail-closed
configuration check. No file behaviour is ported yet; the artefact map below says
exactly what exists.

## The two modes

| | `secure_files` off (default) | `secure_files` on |
|---|---|---|
| Generate with | nothing | `--with secure_files,clamd,worker` |
| `SECURE_FILES` | `False` | `True` |
| Release of a stored file | legacy `withheld()` | clean-only (as layers land) |
| Upload ticket | today's contract | `checksum_sha256` required (as layers land) |
| Scanner, finalizer, scanner schema | absent | generated and active as one unit |
| Missing mandatory setting | not checked | the API and the worker refuse to start |

The mode is a **generation-time** choice. It is the single constant
`koras_api.core.secure_files.SECURE_FILES` (and `koras_worker.secure_files.SECURE_FILES`),
rendered from the capability. It is not a setting, not an environment variable,
and not a runtime toggle. There is no second feature-flag system.

`secure_files` is the **recommended** configuration for any product that stores
customer documents. The default stays off so existing generation output is
unchanged; when a product has `storage` on and `secure_files` off, the CLI prints
a one-line recommendation.

## The compatibility promise

A product generated without `secure_files` is byte-for-byte what it was before the
capability existed, in every file that existed before. The only additions to its
tree are the two inert `secure_files.py` modules (constant `False`, every function
a no-op) and `tests/unit/test_secure_files_config.py`. A generator test asserts
this. Nothing is retrofitted into an existing product, and nothing about an
existing product's downloads changes because the Starter was upgraded.

## Invariants (ADR 0013 section 6)

Once enabled, none of these can be relaxed by a setting, a flag or an environment
variable:

1. Clean-only release.
2. The scanner is mandatory: `FILE_SCAN_BACKEND` is not `none`, no `skipped`
   bypass, no trusted-source bypass.
3. Finalization hashes the incoming bytes and the final copy to the claim and
   requires provenance **equal to the expected upload identity**, not merely
   non-empty.
4. The final key is server-written only.
5. ETag, LastModified and provider checksums are never trust anchors.
6. Every downstream consumer (download, AI, OCR, retrieval, derived content,
   import source) reads bytes only through the release primitive.
7. Restore and replacement begin non-releasable and need a fresh scan decision.

Layer 1 enforces the fail-closed half of (2): a product that cannot name a real
scanner does not start.

## Configuration reference

Mandatory when `secure_files` is on. Both services check them at start and refuse
to start, listing **every** missing or invalid one (names and rules, never
values). There is no fallback to the legacy release.

| Setting | Read by | Requirement |
|---|---|---|
| `FILE_SCAN_BACKEND` | API, worker | a real scanner (`clamd`); `none`, blank and unknown are refused |
| `FILE_SCAN_CLAMD_HOST` | API, worker | set |
| `FILE_SCAN_CLAMD_PORT` | API, worker | an integer, 1-65535 (default 3310) |
| `STORAGE_ENDPOINT` | API, worker | set |
| `STORAGE_BUCKET` | API, worker | set |
| `STORAGE_ACCESS_KEY` | API, worker | set |
| `STORAGE_SECRET_KEY` | API, worker | set |

The incoming and final objects share one bucket and are told apart by key
(`.../incoming/<upload-id>/...`), so the object-storage configuration is the same
four settings for both. The list is the declarative tuple `SECURE_FILES_CHECKS`
in `koras_api/core/secure_files.py`; later layers append entries to it, and the
worker's copy is held identical by a generator test. In the worker, a blank value
reads as absent, like every other sweep setting.

`local/config/secrets.manifest` declares `FILE_SCAN_BACKEND` and
`FILE_SCAN_CLAMD_HOST` as `supplied` and `FILE_SCAN_CLAMD_PORT` as `optional`, in a
product generated with the capability only.

## Artefact map

Capability to generated files. Later layers append rows; every path below is
listed under `template_map.capabilities.secure_files` unless marked "always".

| Layer | Artefact | Generated | Purpose |
|---|---|---|---|
| 1 | `docs/SECURE_FILES.md` (product) | only with the capability | operator page: mandatory settings, how to change the mode |
| 1 | `services/api/koras_api/core/secure_files.py` | always | `SECURE_FILES`, `SECURE_FILES_CHECKS`, `validate_secure_files_settings`, `SecureFilesConfigurationError` |
| 1 | `services/worker/koras_worker/secure_files.py` | always | the same constant and checks for the worker, and `enforce_secure_files_at_startup` |
| 1 | `services/api/koras_api/core/settings.py` | always; scanner fields only with the capability | `file_scan_backend`, `file_scan_clamd_host`, `file_scan_clamd_port` |
| 1 | `services/api/koras_api/main.py` | always; call only with the capability | `validate_secure_files_settings(settings)` first in the lifespan |
| 1 | `services/worker/koras_worker/worker.py` | always; call only with the capability | `enforce_secure_files_at_startup()` first in `on_startup` |
| 1 | `local/config/secrets.manifest` | always; entries only with the capability | `FILE_SCAN_*` |
| 1 | `tests/unit/test_secure_files_config.py` | always | both modes, by switching the constant |
| 1 | generator: `tests/product-secure-files.test.ts` | Starter only | default unchanged, on/off rendering, refusals |

Migrations: none yet. New ones take the next numbers (00039 onward) and stay
semantically identical to Docoris 01016-01019; the mapping will be recorded here
when they land.

## Upgrading an existing product

Nothing is retrofitted. Upgrading the Starter, running `--refresh`, or changing
the Starter's defaults never turns the capability on, and `.koras/project.yaml`
records what the product was generated with.

To adopt it, **regenerate or extend the profile manifest** in `koras-saas-starter`
so that the product's component set includes `secure_files`, `clamd` and `worker`
(plus the `storage`, `tenancy` and `rls` it already has). Do not hand-add the
modules, the constant or the wiring: a hand-edited `SECURE_FILES = True` in a tree
that was not generated for it has none of the schema, the finalizer or the scanner
the constant promises. Generation refuses a configuration missing a dependency:

```
--with secure_files                 -> Component "secure_files" requires "clamd". Enable it as well: --with secure_files,clamd
--with secure_files,clamd --without storage -> requires "storage"
```