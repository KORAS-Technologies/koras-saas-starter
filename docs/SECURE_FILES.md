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
immutable finalization and its digest and provenance checks. **Layer 3** is the
scanner: its schema, its runtime, the finalization-to-scanner hand-off and the sweep that
recovers whatever the hand-off lost. The clean-only release primitive that every
consumer goes through is the next layer; the artefact map below says exactly what exists.

## The two modes

| | `secure_files` off (default) | `secure_files` on |
|---|---|---|
| Generate with | nothing | `--with secure_files,clamd,worker` |
| `SECURE_FILES` | `False` | `True` |
| Release of a stored file | legacy `withheld()` | clean-only (as layers land); a verdict exists from layer 3 |
| Upload ticket | today's contract | `checksum_sha256` required (as layers land) |
| Scanner, finalizer, scanner schema, sweeps | absent | generated and active as one unit |
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

Also mandatory, but with a default that passes, so only a value *outside its range* stops the
product (layer 3; both services check the range and the worker also refuses a value that is not
a number, naming the variable and never the value):

| Setting | Default | Range | What it bounds |
|---|---|---|---|
| `FILE_SCAN_CONNECT_TIMEOUT_SECONDS` | 5 | > 0, at most 60, and not above the next one | time to reach clamd |
| `FILE_SCAN_TIMEOUT_SECONDS` | 120 | > 0, at most 600 | one scan's wall clock |
| `FILE_SCAN_MAX_BYTES` | 104857600 (100 MiB) | 1 to 104857600 | the largest object scanned; lowered here, never raised |
| `FILE_SCAN_MAX_ATTEMPTS` | 12 | 1 to 32767 | the attempt count at which `scan_exhausted` is recorded, once |

The ceiling is not a preference: it is the `StreamMaxLength` the clamd service is built for
(`services/clamd/clamd.conf`), and the sweep's partial indexes (migration 00041) carry the same
number. A larger object cannot be scanned, so it is held `over_ceiling` and stays withheld.

Optional, with bounded defaults, and tuning patience rather than any invariant (none can
make a file releasable that the finalizer or the scanner refused): `FILE_FINALIZE_SWEEP_BATCH`
(default 25, 1-500), `FILE_FINALIZE_RETRY_SECONDS` (default 900, 60-86400) and
`FILE_FINALIZE_MAX_ATTEMPTS` (default 8, 1-100); `FILE_SCAN_SWEEP_BATCH_SIZE` (default 50,
1-500), `FILE_SCAN_SWEEP_MAX_BATCHES` (default 4, 1-20) and `FILE_SCAN_SWEEP_NOT_BEFORE` (an
RFC 3339 instant that can only *narrow* what the sweep selects; absent means everything). The
upload window has no setting, and there is no setting that switches the scanner or its sweep off.

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
* **Decides nothing about the content.** A finalized file is handed to the scanner (below) and is
  exactly as unreleasable as a pending one until the scanner has written a verdict. The clean-only
  primitive that every consumer goes through, and the routing of the consumers other than the
  download route (the assistant's tools, the import engine, restore) through it, is the next
  layer.

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

| Starter | Docoris | What it is |
|---|---|---|
| `00039_file_scan_attempts.sql` (layer 2) | `01016_file_scan_attempts` | four additive columns on `public.files`: `scan_attempts`, `scan_attempted_at`, `scan_failure` with its twelve-word check, `scan_object_etag` |
| `00040_file_scan_interrupted.sql` (layer 3) | `01017_file_scan_interrupted` | the thirteenth word, `scan_interrupted`, and the first sweep index (retired by 00041) |
| `00041_file_scan_due_indexes.sql` (layer 3) | `01018_file_scan_due_indexes` | the two due-time partial indexes the tenant-fair sweep reads; drops 00040's index |
| *the release layer* | `01019_file_derived_content_withdrawal` | not here: it is the release layer's, and takes the next number |

Each is semantically identical to its Docoris original (the SQL bodies are the same; only the
header comments name the Starter), so a later sync of a product that carries 01016-01018 must
find the schemas equivalent. The claim and digest columns (`checksum_sha256`,
`checksum_verified_at`) were already the Starter's, from 00018; the upload id is not a column, it
is the third segment after `incoming/` in the key and the provenance the object carries.

## The scanner (layer 3)

The scanner is the worker's `file.scan` job. It reads a **finalized** object once, through a
bounded and identity-checked reader, asks the clamd service about it, judges the answer with the
product's own integrity and structural gates, and writes a verdict through guarded transitions
that are the only writer of `scan_status` from a scan. It decides content; it does not release.
Release is the next layer's primitive, which reads what the scanner wrote.

### Lifecycle

```
 file.finalize (worker)                    file.scan (worker)                           clamd
 ----------------------                    ------------------                           -----
 incoming key  ──copy, hash x2──▶ final key
 CAS swap, then on_final ───────────────▶ enqueue  scan:<file_id>   (best effort;
                                           │                         a lost one is the sweep's)
                                           ▼
                                  1. read the row as its tenant: ready + pending
                                  2. key must be a FINAL key, else NOT_ELIGIBLE (no read,
                                     no attempt, no write)
                                  3. object gate: window elapsed? size <= ceiling?
                                  4. begin_attempt   (counted BEFORE the read; a crash counts)
                                  5. one bounded stream ──────────────────────────────▶ INSTREAM
                                     feeds: scanner, SHA-256, structural probe        ◀── OK / FOUND / ERROR
                                  6. object identity re-read: unchanged?
                                  7. assess_release = object gate + scanner candidate
                                                    + integrity gate + structural gate
                                  8. transition, by the assessment and by nothing else
                                       INFECTED        -> commit_infected   scan_status infected, status quarantined
                                       CLEAN_ELIGIBLE  -> commit_clean      scan_status clean (evidence required)
                                       HELD            -> record_failure    stays pending, one closed word

 every N minutes  sweep_pending_scans ─▶ re-enqueue what is final, pending and due (back-off
                                          12 m doubling to 1 h, for ever), tenant by tenant
```

### Candidate-clean, exactly

* A scanner `OK` is a **candidate**. `ScanResult` has no `clean`; only an assessment of
  `CLEAN_ELIGIBLE` can build the `CleanEvidence` that `commit_clean` demands, and
  `CleanEvidence` cannot be built unless the object gate passed, the scanner said candidate-clean
  and the structural gate passed.
* **The zip64 gap.** ClamAV 1.4.6 and 1.5.4 do not unpack a deflated, streamed ZIP64 entry and
  can answer `OK` for it (`docs/CLAMD_SERVICE.md`). The structural gate therefore inspects every
  ZIP-family container (ZIP, DOCX, XLSX) without inflating anything, and **holds** that form:
  `inspection_incomplete`, never `clean`, never `infected` on structure alone, never skipped.
  Customer files are not modified or repacked.
* **Integrity.** The digest of the bytes the scanner streamed must equal the provider's own
  SHA-256 when it states one, and equal the row's `checksum_sha256` when `checksum_verified_at` is
  set (the upload finalizer sets it, having hashed the incoming and the final bytes itself). A
  mismatch is `integrity_mismatch`. An ETag is identity evidence and is never compared with a digest.
* **Identity.** `commit_clean` binds the verdict to `scan_object_etag` and refuses an object whose
  size is not the row's, whose key is no longer the one scanned, or that has no ETag to bind to.
* **Infected dominates clean.** A later authoritative infected verdict is not lost to an earlier
  clean one (`clean -> infected` is the one transition out of a final state). Quarantine and its
  security event commit together or not at all; with no audit sink nothing is quarantined.
* **Only a final key is scanned.** An incoming key is one a signed PUT could still write; any key
  that is not exactly the shape the finalizer writes is held with no read. A server-side writer
  that produces a key of another shape (restore, replacement) is the release layer's to bring
  under a scan decision; until then such a file stays `pending`, which is withheld.
* **No scanner text is stored.** Notes are fixed sentences; a signature name is classified and
  dropped by the client and never reaches a column, a log line or an audit detail.

### States and failure words

| Disposition | `scan_status` / `status` | `scan_failure` | Next |
|---|---|---|---|
| `CLEAN` | `clean` / `ready` | cleared | a verdict; the release layer reads it |
| `INFECTED` | `infected` / `quarantined` | cleared | final; the object is kept |
| `HELD` | `pending` / `ready` | one closed word | the sweep retries, with back-off, for ever |
| `DEFERRED` | unchanged | unchanged | nothing was read, counted or written; the window had not elapsed |
| `NOT_ELIGIBLE` | unchanged | unchanged | not this tenant's, not pending, not a final key, or it left `pending` during the run |

The words (`files_scan_failure_check`, migrations 00039 and 00040) are a closed vocabulary of
thirteen: `scanner_unavailable`, `scan_timeout`, `malformed_response`, `scanner_error`,
`object_unreachable`, `object_changed`, `integrity_mismatch`, `over_ceiling`, `misconfigured`,
`scan_limit_exceeded`, `inspection_incomplete`, `identity_insufficient`, `scan_interrupted`.
`scan_exhausted` is deliberately not one: it is an audit action (`storage.object.scan_exhausted`,
a security event) written once when `scan_attempts` reaches `FILE_SCAN_MAX_ATTEMPTS`. The file
stays `pending` and stays in the sweep; exhaustion is a signal for a person, not a limit.

### Attempts, interruption and the sweep

* An attempt is counted **before** the object is read, so a worker killed mid-scan has still counted
  it. `scan_attempts` saturates at the smallint ceiling and never wraps. The finalizer counts its
  own attempts in the same column.
* A cancellation after the attempt is counted (the queue's timeout, a worker stopping) records
  `scan_interrupted`, shielded and best effort, and only on a file that carries no failure: a more
  specific word, from this run or an earlier one, is never replaced. A worker killed outright
  records nothing, and the file is still `pending` for the sweep.
* `sweep_pending_scans` runs every five minutes in the worker. It selects, on the provisioning
  context and by identifier only, files that are `ready`, `pending`, on a **final** key, no larger
  than the ceiling and **due**, and puts the same `file.scan` job back under the same identity. It
  writes no scan state and decides no verdict. Due is `created_at + 1260 s` for a file never
  attempted and `scan_attempted_at + min(720 s * 2^(attempts-1), 3600 s)` otherwise: the first retry
  is longer than the queue's own 660 s job timeout, so a retry never overlaps a run in flight, and the
  back-off caps at an hour and never stops.
* **Tenant fairness.** One tenant's backlog cannot use every slot of a run: the tenant owning the
  oldest due file goes first, tenants follow in id order wrapping round, a page is shared evenly
  over the tenants still open, and spare capacity goes to whoever still has work. The reads are
  index range reads of a few rows on the two partial indexes of migration 00041 (the expression in
  the indexes and in the query is one text, and a test compares them and asks the planner).
* A retained result for the same job id would make the queue refuse a re-enqueue, so the sweep and
  the hand-off drop a stale one first; a job still queued is untouched and collapses.

### Reaching clamd

The worker connects to `FILE_SCAN_CLAMD_HOST:FILE_SCAN_CLAMD_PORT`, the private address of the
`services/clamd` deployment (on Fly, `<app>.internal` over the private network). Nothing a tenant, a
request or a file can say reaches the address, and clamd has no credential. A blank host resolves
to an unavailable scanner, never to a default. `FILE_SCAN_BACKEND=none` is a startup error with no
exception: the API and the worker both refuse to start, and a job that somehow ran with no scanner
would answer `misconfigured` and hold the file. clamd's service descriptor lists the environments
it is deployed to; a product with `secure_files` needs it in **every** environment that runs its
API or worker, because a worker without a reachable scanner holds every file and an API without a
configured one does not start.

### Running the scanner suites

The unit suites need nothing. The integration suites skip, by design, without what they exercise,
and in a product with the capability a skip is a failure (the workflow step above fails on any):

| Variable | For |
|---|---|
| `E2E_DATABASE_URL` | PostgreSQL as the restricted application role (never a superuser: the suites refuse it) |
| `MIGRATE_DATABASE_URL` | the admin connection the planner checks use (`EXPLAIN` of the sweep's reads) |
| `E2E_REDIS_URL` | a Redis, for the queue identity test (default `redis://localhost:6379/5`) |
| `E2E_CLAMD_HOST`, `E2E_CLAMD_PORT` | a running clamd: build `services/clamd` and wait for its `ready: detection self-test passed` line |
| `STORAGE_ENDPOINT`, `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | an S3-compatible store (MinIO) |
| `WORKER_IMAGE` (+ `WORKER_IMAGE_REDIS_URL`, `WORKER_IMAGE_DATABASE_URL`, `WORKER_IMAGE_SERVICES_HOST`, `WORKER_IMAGE_NETWORK`) | the worker image built from the generated Dockerfile |

### What the release layer must consume

The verdict columns and transitions are complete; the release layer plugs into them and writes
none of them.

* `files.scan_status` in `pending | clean | infected | skipped`: only `clean` can ever be releasable,
  and `skipped` is not written by anything in this layer and is not a release.
* `files.status` (`quarantined` with `infected`), `files.scan_object_etag` (the identity a `clean`
  was bound to), `files.storage_key` (the final key the verdict is about; `commit_clean` writes only
  while the row still references it), `files.scan_failure` and `files.scan_attempts`.
* A `clean` row may still become `infected` later (`clean -> infected`); a consumer must read the
  verdict at the moment of release, not cache it.
* The audit actions `storage.object.scanned`, `storage.object.scan_failed`,
  `storage.object.scan_exhausted` (registered by `core/scan_audit.py`) and `storage.object.quarantined`.
* `core/file_scan.py` is the legacy seam (`record_scan`, `withheld`) and is unchanged. The worker
  never calls `record_scan`; in a product with the capability the transitions are the only writer of
  a verdict. `withheld()` still refuses only `infected`; making `pending` withheld everywhere is the
  release primitive's job, and until it lands the download route's incoming-key refusal is what keeps
  an unfinalized file from being served.
* A server-side writer of a key that is not a final key (restore's replacement object, a generated
  export) must either write a final-shaped key or give the scanner a rule of its own for it; the
  scanner reads only a key it can show no ticket was ever signed for.

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
| 3 | `services/worker/koras_worker/scanning/` | capability | the clamd client and protocol (`clamd.py`, `protocol.py`, `result.py`), settings (`config.py`), the bounded identity-checked reader (`objects.py`, `s3.py`), the structural and integrity gates (`structure.py`, `release.py`), the guarded transitions (`transition.py`) and the run that composes them (`runtime.py`) |
| 3 | `services/worker/koras_worker/tasks/scan.py` | capability | the `file.scan` job, and `hand_off_to_scanner`, which the finalizer calls once a file is final |
| 3 | `services/worker/koras_worker/tasks/scan_sweep.py` | capability | `sweep_pending_scans`: tenant-fair, back-off, always on |
| 3 | `services/worker/koras_worker/tasks/finalize.py` | capability | `finalize_one(..., on_final=)`: the hand-off, after the swap and the clearing of the hold |
| 3 | `services/api/koras_api/core/scan_jobs.py`, `scan_enqueue.py`, `scan_audit.py` | capability | the `file.scan` declaration, the one enqueue function, the scanner's audit actions (stdlib and `koras_queue`/`koras_audit` only: the worker image carries them) |
| 3 | `services/api/koras_api/core/upload_window.py` | capability | `is_final_key`: the one statement of which key the scanner reads |
| 3 | `services/api/koras_api/core/secure_files.py`, `services/worker/koras_worker/secure_files.py` | always; checks only with the capability | `SECURE_FILES_CHECKS` gains the scanner's limits; the worker converts a non-number into a refusal that names the variable |
| 3 | `services/api/koras_api/core/settings.py`, `local/config/secrets.manifest` | always; entries only with the capability | `FILE_SCAN_*` limits and the sweep's settings |
| 3 | `services/worker/koras_worker/worker.py`, `services/worker/Dockerfile` | rendered by the capability | binds `file.scan`, schedules `sweep_pending_scans` every five minutes, carries the three API files |
| 3 | `supabase/migrations/00040_file_scan_interrupted.sql`, `00041_file_scan_due_indexes.sql` | capability | see the migration mapping; Docoris 01017 and 01018 |
| 3 | `supabase/tests/350_file_scan_columns_isolation.sql`, `351_file_scan_sweep_selection.sql` | capability | the scan columns' shape, constraint and tenant isolation; the sweep's cross-tenant read and its indexes |
| 3 | `tests/unit/test_scanner_*.py`, `test_scan_*.py`, `scan_transition_support.py`, `scanner_support.py`, `object_support.py`, `zip_support.py`, `eicar_support.py`, `test_file_scan_fixtures.py` | capability | the client against a scripted clamd, the reader, the gates, the transitions, the run, the job, the sweep, the hand-off |
| 3 | `tests/integration/test_scan_transition_real.py`, `test_scan_runtime_real.py`, `test_scan_sweep_real.py` | capability | the transitions, a run and the sweep against PostgreSQL with RLS forced as the restricted role, a real Redis and the planner |
| 3 | `tests/integration/test_scanner_clamd_live.py`, `test_scan_orchestration_real.py` | capability | the client against a real clamd; upload, finalization, hand-off, scan and verdict against PostgreSQL, an S3-compatible store and clamd, all real |
| 3 | `tests/integration/test_worker_image_scanner.py` | capability | the worker image, run with nothing mounted: every scanner module imports, `file.scan` is bound, the sweep is scheduled, and a worker with no valid scanner configuration exits non-zero naming the setting |
| 3 | `.github/workflows/generator-integration.yml` | Starter only | one step on the round-trip row generated with the capability: PostgreSQL, Redis, MinIO and the clamd image built from the generated `services/clamd`; fails on any skip |
| 3 | generator: `tests/product-secure-files-scanner.test.ts` | Starter only | both modes rendered; the scanner halves asserted from the generated text |

**EICAR.** No generated file contains the literal test string (every antivirus that reads a
repository may quarantine it): `tests/unit/eicar_support.py` holds it base64-encoded and
`materialize()` decodes it, checked against its recorded SHA-256, on every call.

Migrations: 00039 (layer 2), 00040 and 00041 (layer 3). New ones take the next numbers and
stay semantically identical to Docoris 01016-01019; the mapping is recorded above.

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