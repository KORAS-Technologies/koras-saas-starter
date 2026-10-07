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
here layer by layer. **Layer 1** is the scaffold: the capability, its generation
switches, the generated constant and the fail-closed configuration check.
**Layer 2** is the upload foundation: the SHA-256 claim, the incoming key, the
immutable finalization and its digest and provenance checks. The scanner, the
structural gates and the clean-only release are later layers; the artefact map
below says exactly what exists.

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
| `REDIS_URL` | API, worker | set: a confirmed upload is finalized by a job (layer 2) |
| `DATABASE_URL` | API, worker | set: the finalizer works on the file's row as its tenant (layer 2) |
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

Optional, with bounded defaults, and tuning patience rather than any invariant (none can
make a file releasable that the finalizer refused): `FILE_FINALIZE_SWEEP_BATCH`
(default 25, 1-500), `FILE_FINALIZE_RETRY_SECONDS` (default 900, 60-86400) and
`FILE_FINALIZE_MAX_ATTEMPTS` (default 8, 1-100). The upload window has no setting.

`local/config/secrets.manifest` declares `FILE_SCAN_BACKEND` and
`FILE_SCAN_CLAMD_HOST` as `supplied` and `FILE_SCAN_CLAMD_PORT` as `optional`, in a
product generated with the capability only.

## The upload contract (layer 2)

One API and one request model. `checksum_sha256` is the only thing that differs, and it
differs by the generated constant, not by a switch.

| | `secure_files` off (the default) | `secure_files` on |
|---|---|---|
| `checksum_sha256` on `POST /api/v1/files/uploads` | optional, `null` or absent allowed; never a trust anchor | **required**: exactly 64 lowercase hex characters |
| Uppercase, short, long or non-hex | 422 | 422 |
| Where the claim lives | nowhere: signed into the URL when sent | on the file's row, bound at issuance, never written again |
| The key the ticket is signed for | `tenants/<t>/<category>/<file>/<name>` | `tenants/<t>/<category>/<file>/incoming/<upload-id>/<name>` |
| Headers the ticket signs | `Content-Type`, and `x-amz-checksum-sha256` when a digest was sent | the same, plus the copy-source guard and the upload id (below) |
| `POST /files/{id}/complete` | records the client's digest as a claim and asks the provider whether it agrees | records nothing: refuses a body digest that is not the bound one (422 `upload_checksum_claim_invalid`) and a row with no bound claim |
| After the response | hands the file to the registered upload hooks with a signed URL | enqueues `file.finalize`, deferred to the end of the upload window; **no URL is signed and no hook is called** |
| `GET /files/{id}/download` on an incoming key | allowed (when not infected) | 403 `file_quarantined`, before anything is signed |

The server never invents a claim: a digest read from the object after the upload would vouch
for whatever was written. A row without one is refused at completion and held by the
finalizer.

### Request and response, off

```http
POST /api/v1/files/uploads
{"name": "report.pdf", "size_bytes": 12, "content_type": "application/pdf"}

201
{"file_id": "...", "upload_url": "https://...", "method": "PUT",
 "headers": {"Content-Type": "application/pdf"}, "expires_in": 900}
```

### Request and response, on

```http
POST /api/v1/files/uploads
{"name": "report.pdf", "size_bytes": 12, "content_type": "application/pdf",
 "checksum_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}

201
{"file_id": "...", "upload_url": "https://.../incoming/<upload-id>/report.pdf?X-Amz-...",
 "method": "PUT", "expires_in": 900,
 "headers": {
   "Content-Type": "application/pdf",
   "x-amz-checksum-sha256": "<base64 of the digest>",
   "x-amz-copy-source-if-match": "\"00000000000000000000000000000000\"",
   "x-amz-copy-source-if-unmodified-since": "Thu, 01 Jan 1970 00:00:00 GMT",
   "x-amz-metadata-directive": "COPY",
   "x-amz-meta-koras-upload": "<upload-id>"}}

POST /api/v1/files/uploads            (no checksum_sha256)   -> 422, field named
POST /api/v1/files/uploads            (checksum_sha256 "AB..") -> 422
```

The response has the same five fields in both modes. The browser must send exactly the
headers it was given: they are part of the signature, so adding, removing or rewriting one is
refused by the provider.

### Topology

```
 browser                    API                         bucket                      worker
 -------                    ---                         ------                      ------
 sha256(file)  ──claim──▶  insert files row
                           (checksum_sha256, key =
                            .../incoming/<upload-id>/..)
                           sign PUT for that key only
               ◀─ticket──  (+ copy-source guard,
                            + x-amz-meta-koras-upload)
 PUT ────────────────────────────────────────────────▶ incoming/<upload-id>/name
 complete ───────────────▶ head(): size matches?
                           status = ready (scan_status pending)
                           enqueue file.finalize
                           (delayed FINALIZE_DELAY_SECONDS)  ─────────────────────▶ after the window:
                                                                                     1. provenance == <upload-id>  (exact)
                                                                                     2. sha256(incoming) == claim
                                                                                     3. copy ──▶ final/<generation>/name
                                                                                     4. sha256(final) == claim
                                                                                     5. CAS swap files.storage_key
                                                                                     6. delete incoming (best effort)
```

A client can write only an incoming key, and only through a signed ticket. A final key is
written only by the worker, under a fresh generation per attempt, so a client can never name,
overwrite or race it. Nothing the provider says (ETag, LastModified, a stored checksum) is
evidence of the bytes: the digests are computed over the bytes this process read.

### What finalization guarantees, and what it does not

* **Exact provenance.** The object must carry the ticket's own upload id, equal to the one in
  its incoming key, not merely something. A provider copy carries its source's metadata.
* **Both digests.** The incoming bytes and the final copy are each hashed and compared with the
  claim. A late write to the incoming key cannot change the final object.
* **Compare-and-set.** The swap applies only while the row is `ready`, `pending` and still on
  that incoming key, so two racing attempts leave one owner and one referenced object.
* **Ambiguous commits.** If a commit raises, the final object is deleted only when the row is
  read back and does not reference it; when that cannot be established it stays, an orphan for
  reconciliation, never a referenced object removed.
* **Held, not failed open.** Any refusal records a closed `scan_failure` word on the file
  (`integrity_mismatch` for a digest or provenance that is not the claim's) with one
  `storage.upload.held` audit event when the word is new or changed, deletes anything the
  attempt wrote, and leaves the file `pending` on its incoming key. `integrity_mismatch` is
  never retried; every other reason is retried after a back-off, up to
  `FILE_FINALIZE_MAX_ATTEMPTS`, and then waits for a person.
* **Fail closed.** If the queue is down, the worker is down, the store is unreachable or the
  job is lost, the file is on an incoming key with `scan_status = 'pending'`: the download
  refuses it, no hook is handed it, and backup does not copy it. The worker's sweep
  (`sweep_finalize`, every five minutes) finalizes whatever no job did.
* **Not yet.** Finalization does not decide anything about the content. Making a file
  *releasable* (the scanner, the structural gates, the clean-only primitive every consumer goes
  through) is a later layer. Until it lands, a finalized file is exactly as unreleasable as a
  pending one, and consumers other than the download route (the assistant's tools, the import
  engine, restore) are not yet routed through a release rule.

The upload window is not a setting: `UPLOAD_URL_SECONDS` (15 min), the 60 s margin and the
measured 180 s in-flight bound are constants in `core/upload_window.py`, and
`FINALIZE_DELAY_SECONDS` (19 min) is their sum. No environment variable shortens them.

### The bucket

The browser PUTs the ticket's headers cross-origin, so the bucket's CORS rule must allow the
`PUT` method and these request headers: `Content-Type`, `x-amz-checksum-sha256`,
`x-amz-copy-source-if-match`, `x-amz-copy-source-if-unmodified-since`,
`x-amz-metadata-directive`, `x-amz-meta-koras-upload`. A rule that does not fails the upload at
the preflight, which is the safe direction.

### Migration mapping

`supabase/migrations/00039_file_scan_attempts.sql` is semantically identical to Docoris
`01016_file_scan_attempts` (four additive columns on `public.files`: `scan_attempts`,
`scan_attempted_at`, `scan_failure` with its twelve-word check, `scan_object_etag`). The
claim and digest columns (`checksum_sha256`, `checksum_verified_at`) were already the
Starter's, from 00018; the upload id is not a column, it is the third segment after
`incoming/` in the key and the provenance the object carries. Docoris `01017` (the thirteenth
word `scan_interrupted` and the sweep index), `01018` and `01019` belong to the scanner and
release layers and are not here yet; when they land they take the next numbers and a later
sync of a product that carries 01016-01019 must find the schemas equivalent.

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
| 2 | `services/api/koras_api/core/upload_window.py` | capability | ticket lifetime, the 60 s margin, the in-flight bound, `FINALIZE_DELAY_SECONDS`, the incoming and final key shapes (stdlib only: the worker image carries it) |
| 2 | `services/api/koras_api/core/finalize_jobs.py` | capability | the `file.finalize` declaration, its identity and its one-id payload |
| 2 | `services/api/koras_api/core/finalize_enqueue.py` | capability | enqueue after the response, deferred to the end of the window; a failed enqueue never fails the upload |
| 2 | `services/api/koras_api/core/upload_audit.py` | capability | the `storage.upload.finalized` and `storage.upload.held` actions |
| 2 | `services/api/koras_api/routers/files.py` | rendered by the capability | the one upload router: required claim, incoming key, guard headers, bound-claim completion, finalizer hand-off, incoming-key download refusal |
| 2 | `services/api/koras_api/core/errors.py` | rendered by the capability | `UPLOAD_CHECKSUM_CLAIM_INVALID`, present only with the capability (the web tier answers it with its status fallback, so the shared i18n catalogue is untouched) |
| 2 | `python-packages/koras-storage` | always, additive | `upload_guard_headers`, `UPLOAD_PROVENANCE_META`, `S3ObjectStore.provenance()`, `S3ObjectStore.sha256()`, and `presign_upload(..., provenance=None)`; a product that never passes `provenance` signs what it always signed |
| 2 | `services/worker/koras_worker/uploads/{finalize,_audit}.py` | capability | `UploadFinalizer`: provenance, both digests, copy, compare-and-set swap, ambiguous-commit handling, cleanup |
| 2 | `services/worker/koras_worker/tasks/finalize.py` | capability | the job (`file.finalize`), the five-minute sweep, attempt counting, hold recording |
| 2 | `services/worker/koras_worker/worker.py` | rendered by the capability | binds the job by name, schedules `sweep_finalize` |
| 2 | `services/worker/koras_worker/tasks/storage_backup.py` | always | `_due_query(secure_files)`: with the capability, backup never selects an incoming key |
| 2 | `services/worker/Dockerfile`, `services/worker/pyproject.toml` | rendered by the capability | the API files the finalizer reaches by name, and `koras-audit` |
| 2 | `supabase/migrations/00039_file_scan_attempts.sql` | capability | `scan_attempts`, `scan_attempted_at`, `scan_failure` (closed vocabulary), `scan_object_etag`; Docoris 01016 |
| 2 | `supabase/tests/340_upload_finalization_isolation.sql` | capability | the finalizer's statements under forced RLS: own row only, compare-and-set, closed vocabulary |
| 2 | `packages/api-client/src/upload-claim.ts` (+ `.test.ts`) | capability | `digestOf`: the browser's SHA-256, which throws rather than return a partial claim |
| 2 | `apps/web/src/lib/browser-upload.ts`, the Files and import panels and their actions | rendered by the capability | the first-party client computes and sends the claim; without the capability the client is unchanged |
| 2 | `tests/unit/test_upload_ticket_contract.py` | always, per mode | the contract in whichever mode the product was generated in |
| 2 | `tests/unit/test_upload_finalization.py`, `test_upload_finalize_task.py`, `upload_store_support.py` | capability | key shapes, ticket and completion, the job and sweep edge |
| 2 | `tests/integration/test_upload_finalization_real.py`, `test_upload_checksum_provenance_real.py` | capability | the finalizer against a real PostgreSQL with RLS forced |
| 2 | `tests/integration/test_upload_finalization_provider.py`, `test_upload_checksum_provider.py` | capability | the provider attack matrix, including the forged-provenance regression (ADR 0013 section 9), against a real S3-compatible store |
| 2 | generator: `tests/product-secure-files-upload.test.ts` | Starter only | both modes rendered, each half asserted from the generated text |

Migrations: 00039 (layer 2, above). New ones take the next numbers and stay
semantically identical to Docoris 01016-01019; the mapping is recorded above.

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