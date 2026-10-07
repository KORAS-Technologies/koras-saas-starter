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
recovers whatever the hand-off lost. **Layer 4** is the release layer: the one clean-only
primitive that every consumer goes through, the consumers wired to it, and the withdrawal of
derived content when a file stops being releasable. **Layer 5** is restore and replacement: a
restored object is a new final-shaped object that begins non-releasable and gets a fresh scan
decision. The artefact map below says exactly what exists.

## The two modes

| | `secure_files` off (default) | `secure_files` on |
|---|---|---|
| Generate with | nothing | `--with secure_files,clamd,worker` |
| `SECURE_FILES` | `False` | `True` |
| Release of a stored file | legacy `withheld()`, reached through the one rule | clean-only, for this tenant's own final object, for **every** consumer (layer 4) |
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

A product generated without `secure_files` behaves as it did before the capability existed, and
every file that existed before is byte-for-byte what it was **except** these, each of which is a
no-op without the capability:

* layers 1-3: the two inert `secure_files.py` modules (constant `False`, every function a no-op) and
  `tests/unit/test_secure_files_config.py`;
* layer 4: `core/file_release.py` (the one rule, which answers exactly as the platform seam does
  when the constant is `False`), and four tests of it (`test_file_release.py`,
  `test_files_release_api.py`, `test_release_bypass_guards.py`, `release_support.py`); in
  `routers/files.py`, the download asks that rule instead of calling `withheld()` directly (two
  lines, the same answer for every stored state, asserted by a test over all of them); and twelve
  sentences added to each of the three message catalogues (`en`, `de`, `es`), which nothing renders
  without the capability; and, in a product with `data_import`, `tests/integration/test_worker_image.py`
  recognises a product with the capability (by the upload window module) and gives the image's worker
  the settings that product refuses to start without -- an `if` that is never taken here.
* layer 5: `tasks/storage_restore.py` and `tests/unit/test_storage_restore.py` become templates whose
  rendering **without** the capability is the previous text, byte for byte (a generator test
  generates the default product at the previous commit and now and compares); `tests/unit/test_release_bypass_guards.py`
  and `test_scan_task.py` register the restore writer and enqueuer, which a product without the
  capability does not have; and `upload_window.py` and `scan_enqueue.py` are the capability's own.

The rest of what the capability changes in a shared module is rendered by the capability, so a
product without it carries the original text. Without `ai`, `data_import` or `worker` the modules
that belong to them are not generated at all. A generator test asserts this, and
`docs/SECURE_FILES.md` lists every file the capability renders (the artefact map). Nothing is
retrofitted into an existing product, and nothing about an existing product's downloads changes
because the Starter was upgraded.

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
  download route (the assistant's tools, the import engine) through it, is layer 4; what a
  restore writes is layer 5 ("Restore and replacement" below).

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
| `00042_file_derived_content_withdrawal.sql` (layer 4) | `01019_file_derived_content_withdrawal` | a trigger on `public.files`: when a `ready` + `clean` file stops being so, its chunks are deleted and its index state cleared in the same statement. One difference, stated in the file: the delete is skipped where the product has no `ai_knowledge_chunks` (`to_regclass`), because a product may have `secure_files` without the assistant |

Each is semantically identical to its Docoris original (the SQL bodies are the same; only the
header comments name the Starter, and 00042's one guard is described above), so a later sync of a product that carries 01016-01019 must
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
  that produces a key of another shape is the release layer's to bring under a scan decision; the
  one that exists (a restore's object) writes the final shape itself (layer 5), so the scanner
  needs no rule of its own for it.
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
  a verdict. `withheld()` still refuses only `infected`, and stays the legacy rule; with the
  capability nothing consults it (layer 4: see "The release layer" below).
* A server-side writer of a key that is not a final key must either write a final-shaped key or
  give the scanner a rule of its own for it; the scanner reads only a key it can show no ticket was
  ever signed for. Restore is the one such writer and it writes a final-shaped key
  ("Restore and replacement" below).

## The release layer (layer 4)

`koras_api/core/file_release.py` is **the** rule, and it is generated in both modes. Every consumer
that hands out, reads or derives from a file's bytes asks it, and nothing else; a static guard
(`tests/unit/test_release_bypass_guards.py`) fails when one does not.

### The rule, per mode

The branch is the generated constant `SECURE_FILES` and nothing at run time. There is no setting, no
environment variable and no fallback that moves a secure product onto the legacy rule.

| Same stored row | `secure_files` off | `secure_files` on |
|---|---|---|
| `clean`, on a finalized key, stamped by the scanner | released | released |
| `pending`, `skipped`, no value, an unrecognised value | released to a download (`withheld()` refuses only `infected`); refused to an import source | **refused** |
| `infected` / `quarantined` | refused | refused |
| `clean` but on another tenant's key, a ticket's incoming key, or with no scanner stamp | released (no identity is consulted: a product that never had the scanner has neither) | **refused** |

Without the capability the answers are the platform seam's own: a download is withheld by
`core/file_scan.WITHHELD`, and an import source by its own narrower deny-list; the rule reproduces
both (a test holds them to the originals), so a product's behaviour is what it was.

With the capability the rule is strict equality on `status = 'ready'` and `scan_status = 'clean'`
(so `None`, `"CLEAN"`, `"clean "`, a number or a list refuses) **and** an identity:

1. the row's tenant is the tenant the caller is acting for;
2. `storage_key` is a *final* key (`tenants/<tenant>/<category>/<file>/final/<generation>/<name>`,
   the one shape only a worker writes after finalization) whose tenant segment is that same tenant,
   so a row cannot be pointed at another tenant's object;
3. `scan_object_etag` is present: the scanner's `clean` transition writes it and nothing else does.

A consumer that cannot supply the identity gets `False`. The same sentence is spelled once for a
statement (`RELEASABLE_SQL`) and a test runs both spellings over every `status`, every `scan_status`
and every way an identity can be wrong, against a real PostgreSQL. Layer 3's scanner already refuses
to read any key that is not final, so a clean row on any other key could only have been written by
something other than the scanner; layer 4 holds the consumers to the same line.

### The release path

```
 upload ticket ──▶ incoming key ──▶ finalize (hash, provenance, copy) ──▶ final key ──▶ scanner
   (claim)          a PUT can             worker only                       no ticket     clamd + gates
                    still write it                                          was signed
                                                                                │
                              pending ──────────────────────────────────────────┤ commit_clean
                                 │   (every consumer refuses)                   ▼
                                 │                                  ready + clean + stamp  ◀── the ONLY
                                 │                                          │                    releasable state
        ┌────────────────────────┴───────────────┬───────────────┬──────────┴──────┬─────────────────────┐
        ▼                                        ▼               ▼                 ▼                     ▼
  GET /files/{id}/download                  GET /files       the assistant      retrieval and      import source
  require_releasable                        content_available  index_clean_file  conversation       check_source
  signs only on a yes                       + hook offers      read_releasable    replay             releasable(...)
                                                                reads only on     RELEASABLE_SQL     before one byte
                                                                a yes             in the statement   is parsed

  clean ──▶ infected | not ready | archived | deleted    =  the trigger in 00042 deletes the file's
                                                            chunks and clears its index state in the
                                                            SAME statement, and every consumer above
                                                            reads the verdict again at the moment it reads
```

### Consumers

Every row names how the consumer asks. "Gate" is `core/file_release_gate.py` (API only, generated
with the capability): `require_releasable` for a person's request, `read_releasable` for a process
that reads the object itself.

| Consumer | File | With `secure_files` | Without |
|---|---|---|---|
| Download | `routers/files.py` | `require_releasable(..., consumer="download")` before anything is signed; one denied event per refusal (`storage.object.release_refused`, or `storage.object.quarantined` for infected), closed reason and consumer only | `releasable()` (the platform deny-list) |
| Files list | `routers/files.py` | `content_available` per file, from the same row check; a file is offered to a hook only when releasable | as it was (no field) |
| Upload completion | `routers/files.py` | signs nothing, offers nothing to a hook; the answer says `content_available: false` | signs one URL for the interested hooks |
| File hooks | `core/file_hooks.py` | `after_clean` + `due`; there is no `after_upload` and no URL, a hook that tried to register one does not construct | `after_upload` |
| Assistant indexing | `core/file_indexing.py`, `core/ai.py` | `index_clean_file`: `read_releasable(consumer="indexing")`, then the write is bound to the object that was read (storage key and stamp) | `index_uploaded_file` (fetches a URL) |
| Chunk writes | `core/knowledge.py` | `index_file_document`: a share lock on the file's row, the rule asked inside the transaction, the object compared again | `index_document` |
| Retrieval | `core/knowledge.py` | the search statement carries `RELEASABLE_SQL`: a chunk of a file that is not releasable is never returned, nor one whose file row is gone | ungated |
| Conversation replay | `core/ai.py` | a stored search result is re-filtered at read time; a passage survives only if its file is releasable now | as it was |
| Assistant file tool | `ai/tools.py` | `content_available` from the row check, so a file still being checked is not described as readable | name and size only |
| Import source | `core/imports.py` (and the worker's `tasks/imports.py`, which calls it) | `releasable(consumer="import")` in `check_source`, before the object is fetched; the session's own tenant is the one the row is held to | `UNPARSEABLE_SCANS` |
| Backup, reconcile, lifecycle | `tasks/storage_backup.py`, `storage_reconcile.py`, `storage_lifecycle.py` | custody, not release: they copy, list or delete objects and hand nobody their bytes; the backup never selects an incoming key (layer 2) | the same |
| Restore | `tasks/storage_restore.py` | custody, not release, and a *writer*: the object it writes is a new final-shaped one and its row is reset to `pending`, so nothing releases it until a fresh scan decision (layer 5, below) | the legacy restore, unchanged |
| Exports and generated artefacts | `routers/audit_exports.py`, `reporting_schedules.py` | not files: they live in their own tables with their own expiry and are served from their own routes, so no `public.files` row is ever created for one and nothing can release them through this rule | the same |

### Server-side writers of a key that is not final

Two kinds, and neither can ever become releasable through the release rule on the strength of
anything but the scanner:

* **Exports and generated artefacts** write to the bucket but create no `public.files` row. There is
  nothing for the rule to decide, and `test_release_bypass_guards.py` lists each read of one by file
  and reason, so a new one is a failing test until it is accounted for.
* **A restore's object** (layer 5) is a `public.files` row. It is written `pending` on a
  final-shaped key, and stays withheld until the scanner has made a fresh decision about the object
  it now names ("Restore and replacement" below).

### What is withdrawn, and when

Migration `00042_file_derived_content_withdrawal.sql` (Docoris 01019) is a `BEFORE UPDATE` row trigger
whose `WHEN` clause fires for nothing but `ready` + `clean` -> anything else, and a `BEFORE DELETE`
trigger for the row going. In the same statement it deletes the file's chunks (the tenant is named,
so it can only remove its own tenant's) and clears `indexed_at` and `index_note`. A late `clean ->
infected` verdict, a restore's `clean -> pending`, and an archive all do this whichever module writes
them; the scanner does not know the assistant exists. The function is `SECURITY DEFINER` with a
pinned `search_path`, takes no argument, and is callable by nobody. The indexer's share lock on the
file's row serialises with the scanner's `select ... for update`, so an index write racing a verdict
ends with no usable chunk in either order.

### Settings

None. `SECURE_FILES_CHECKS` needs nothing new: the rule reads no setting, and the scanner, storage,
queue and database settings it stands on were already mandatory.

### Running the release suites

`tests/unit/test_file_release.py`, `test_files_release_api.py` and `test_release_bypass_guards.py` run in
both modes and need nothing. `tests/integration/test_file_release_real.py`,
`test_file_derived_content_real.py` and `supabase/tests/360_file_derived_content_withdrawal.sql` need
a database: the first two skip without `E2E_DATABASE_URL` (the restricted role, as for the scanner
suites) and in a product with the capability a skip is a failure. Run the unit and the integration
modules in separate `pytest` invocations: the integration modules point the API's own engine at the
database named by the variable, which an earlier unit module's import has already fixed.

## Restore and replacement (layer 5)

`tasks/storage_restore.py` (rendered by `secure_files`) is the one worker task that writes bytes
back into the bucket and changes which object a `public.files` row names. The legacy restore reused
the original key and set the row `ready`: for a file that had been released as `clean` that changes
the bytes under a standing verdict, and a signed URL issued for the old bytes would read the new
ones. With `secure_files` it does neither. It was proven in Docoris (OD-10 S3, with the scanner
follow-up) and is generalized here; ADR 0013 section 6 item 7 is the invariant ("restore/replacement
begins non-releasable and needs a fresh scan decision").

### The two modes, and the dependency

| | `secure_files` off | `secure_files` on |
|---|---|---|
| Overwrite of an existing file | writes the **original key**, updates size, checksum and `status = 'ready'` (as before; byte for byte the same text) | **never** writes the original key: a new final key, the row switched in one statement |
| A restored copy (no overwrite) | `tenants/<t>/<category>/<new id>/<name>`, row `ready`, scan columns at their defaults | `tenants/<t>/<category>/<new id>/final/<generation>/<name>`, the same defaults, and a scan is asked for |
| What the row carries afterwards | the old scan columns, untouched | `pending`, with no verdict, note, attempts, failure, **`scan_object_etag`**, index state or chunks; backup and archive state reset |
| Asking the scanner | n/a (a scanner is optional) | `restore_scan.py`: one job under the scan's own identity, plus a follow-up for a lost request |

`secure_files` **requires** `storage` and the worker; **restore** is `storage_governance`'s. The
two are independent switches and the decision is explicit:

* `secure_files` on, `storage_governance` on (the default product has it): the restore described
  here, and `restore_scan.py` with its suites, are generated.
* `secure_files` on, `storage_governance` **off**: the product has *no restore at all* (no route,
  no table, no worker task), so there is nothing to bring under the rule and nothing is generated for
  it. A product that later adds `storage_governance` must be regenerated, and gets the secure
  restore, because the capability's rendering is decided by the generated constant and not by which
  other capabilities are present.
* `secure_files` off, `storage_governance` on: exactly the Starter's existing restore (the
  generator tests compare the rendering with the previous commit's).

### The replacement, step by step

```
 approved request ──▶ read the backup copy, hash it, compare with the digest the backup recorded
        │                (no match: the object stays gone, nothing is written)
        ▼
 lock the file's row as its tenant, decide on the row as it is now (`replacement_refusal`)
        │   infected / quarantined ............... refused: "restore as a new object"
        │   pending or skipped, any status ....... refused: a scan may be running on the old bytes
        │   a scan attempt inside the horizon .... refused: it may still be finishing
        │   not ready/archived/deleted/purged .... refused
        ▼
 write the bytes to a NEW key, `.../<file>/final/<fresh generation>/<name>`, asking the provider
 to check the SHA-256, then READ IT BACK and hash it again (`_write_verified`)
        │   mismatch: delete the new object, change nothing
        ▼
 in ONE statement, only if the row is still as it was read (storage key, status, scan status):
   storage_key = new key, size, checksum = the digest this worker computed, checksum_verified_at = now
   scan_status = 'pending', scan_note / attempts / attempted_at / failure / scan_object_etag cleared
   indexed_at / index_note cleared, backup_status = 'none', backed_up_at / archived_at cleared
 and, with the assistant, the file's chunks are deleted in the same transaction
        │   anything fails: the transaction rolls back and the new object is removed
        ▼
 commit ──▶ `restore_scan`: enqueue the scan for this file (after the commit; never raises)
```

* **No unsafe overwrite.** The old key is never an argument to the write; a test inspects the module
  for it, and the old object is neither overwritten nor deleted. A URL signed for it keeps reading
  the old bytes and nothing else. Nothing reclaims the old object: reconciliation reports an
  unreferenced object and removes none, so it stays until an operator removes it.
* **Identity binding.** The release rule needs a final key of the row's own tenant and a
  `scan_object_etag`, which only the scanner's `clean` transition writes and which the replacement
  clears. The old (key, etag) pair therefore cannot release the new bytes, and the new bytes cannot
  be released on the old verdict: the scanner's `commit_clean` binds the verdict to the key it read
  and writes only while the row still references it.
* **A fresh scan decision.** The key is exactly the shape of a finalized upload
  (`upload_window.final_key`), so the scanner reads it without a rule of its own. The scanner's
  read gate (the upload window, from the row's `created_at`) applies to a new row, so its job is
  enqueued after the window; a replaced file is old and is asked for at once.
* **Integrity.** The digest compared is the backup run's recorded one where there is one (a copy that
  does not match is a failure and the object stays gone). Where none was recorded the restore still
  runs, because refusing would refuse the only copy of an object whose provider never computed one,
  and the audit row says plainly that nothing was compared (`verified: false`). Beyond Docoris's
  proven behaviour, the written object is read back and hashed before any row names it, and the
  row's `checksum_verified_at` is set from that, so the scanner also compares the digest of the bytes
  it streams with the row's.
* **A lost request is not a lost file.** The file is `pending` on a final key, which the scan sweep
  selects by itself; `reconcile_restored_scans` also looks at the restores of the last seven days for
  a file still `ready` and `pending` and owed an attempt, because the sweep can be narrowed by
  `FILE_SCAN_SWEEP_NOT_BEFORE` and a replaced file is an old file. Nothing is written by it and no
  verdict is decided: `restore_scan.py` is an enqueuer and a reader (a static test holds it to that),
  and the scanner's guard on who may name the scan task lists it by name.
* **An ambiguous commit never deletes the live object.** If the commit raises, the outcome is read
  back from the database (`commit_outcome`), under the request's own row lock; the object is removed
  only on proof that nothing committed.
* **Closed refusals.** A refusal's code goes into the audit row and its sentence into the request's
  `error`; neither carries a name, a key or a digest.

### What differs from Docoris, and what was left out

* The key shape: Docoris's scanner also scans a legacy-shaped key when a completed restore names the
  file; the Starter's scanner reads only a final key, so the restore writes one. A restored *copy*
  is final-shaped too.
* No scanner-activation check in `restore_scan`: with `secure_files` the scanner is mandatory and the
  product does not start without it.
* The write is verified, and read back (above).
* `file_backups` is joined on the request's own tenant and file in `_APPROVED` (the sweep reads on the
  provisioning context, which sees every tenant) in the secure rendering.
* Docoris's **legacy remediation** (GR-370: re-trusting historical rows, restore-provenance retrust,
  `restore_provenance_support.py`, the `_RESTORED` scanner path) is Docoris-only history and is not
  ported.
* **Migrations.** Docoris's `00026_restore_requests.sql` and `250_restore_isolation.sql` are identical
  to the Starter's own; no migration is added. The replacement relies on layers 2-4's columns
  (`scan_attempts`, `scan_attempted_at`, `scan_failure`, `scan_object_etag`) and 00042's withdrawal
  trigger.
* The legacy rendering still has the legacy `_APPROVED` join and a `_TOUCH_FILE` overwrite; they are
  not changed here (byte-identical rendering was the requirement), and are listed as follow-ups.

### Running the restore suites

`tests/unit/test_storage_restore_replacement.py`, `test_restore_scan.py` and the rendered
`test_storage_restore.py` need nothing. `tests/integration/test_restore_replacement_real.py` (and
`test_restore_derived_content_real.py` with the assistant) need `E2E_DATABASE_URL`;
`test_restore_orchestration_real.py` also needs the store (`STORAGE_*`) and a scanner
(`E2E_CLAMD_HOST`), and runs the real finalizer, restore, scan job and release gate. In a product
with the capability a skip is a failure (the generator-integration step fails on any).

## Import activation (layer 6a)

ADR 0013 section 7 makes the import activation gate (proven in Docoris) a generic Starter
facility. It is **not secure_files-specific**: it ships with the `data_import` capability, in
both file modes, because an import writes a customer's records in bulk and the source file is a
second upload surface.

### Default and compatibility

**OFF in every environment.** Absent, blank, `false`, a typo, a number: all off. Only
`true`, `1`, `yes` or `on` (any case, surrounding spaces ignored) switches it on, parsed by the one
function `koras_import.parse_import_activation` that the API and the worker both call, so the two
cannot disagree. There is no path from an unparseable value to "on".

A product generated with `data_import` therefore starts with imports **off** until its
deployment declares and sets the switch. Existing products are not retrofitted: generated code
changes only on regeneration or an explicit sync, exactly as for `secure_files` (see "Upgrading an
existing product"). A product that already has `data_import` and imports today gets the gate when
it regenerates, and must activate each environment it uses; the sync is the moment to do so.

### What enforces it

| Where | How | Refusal |
|---|---|---|
| API, every route of `routers/imports.py` | one router-level dependency, `require_import_activation`, so a route added later inherits it. Runs after authentication, tenant resolution and the `imports.manage` check; an anonymous caller still gets 401 and a caller without the permission the ordinary 403, and neither learns the switch's state | `403 import_not_enabled`, the same words on every route; the file is never opened. A mutating request writes one `import.refused` audit row (route template and reason only); reads write none |
| Worker, both tasks (`imports.validate`, `imports.commit`) | `_refuse_while_disabled` is the first statement after `del ctx`, before the heavy gate, the registry or the object store. Checked **when the job starts**, so a job enqueued while ON that runs after the switch is turned OFF is refused, and a job enqueued directly (not through the API) cannot bypass the API's check | answers `{"status": "refused", "reason": "activation_disabled"}`; a run stranded in `validating` / `commit_requested` / `committing` is moved to `failed` through the same guarded `abandon` a cancelled job uses, and an `import.refused` audit row is written. A recording failure is logged and the job is still refused |
| Web | `api-errors` maps `import_not_enabled` to a sentence; the page shows its error banner. The UI never enforces | |

Guards in `tests/unit/test_import_activation_gate.py`: the router's eleven routes are listed and
driven, with a body that would be a 422 if the gate ever ran after validation; the gate is on the
router; only the router and the task module may name the two job definitions, the run store's
source and commit entry points, the task bodies or the task names as strings; every public task
function that takes an envelope starts with the gate. Both processes are tested with absent,
blank, malformed and explicit values.

### Declaring it per environment

`local/config/import-activation.yaml` is rendered for `data_import` products with the four
environments `disabled`:

```yaml
environments:
  dev:
    import_activation: disabled   # enabled | disabled, nothing else
  test:
    import_activation: disabled
  stg:
    import_activation: disabled
  prod:
    import_activation: disabled
```

`disabled` means **absent**: the environment holds no `IMPORTS_ENABLED` at all. The setting is
declared `IMPORTS_ENABLED optional - bool` in `local/config/secrets.manifest` (never `supplied`;
absent must mean off) and is read from the process environment like every other setting, so the
secret store the estate uses (Doppler) is where an environment's value lives. To activate
an environment: commit `enabled` for it, set `IMPORTS_ENABLED` to `true` in that environment's
secret-store config before the merge that deploys it. To deactivate: commit `disabled`, remove the
key, and unset it on any service that holds it directly. Locally, set it in `.env.local`; nothing
else turns it on, and `make dev` does not.

`local/scripts/import-activation-drift.sh <app> <secret-store-project> <config>` is run by the
generated `deploy.yml` before each service deploys (a no-op in a product without the
declaration). The deploy imports the secret store into the app and never removes a secret, so a value
set by hand on an app would outlive every deploy; the script fails the deploy when an app holds
`IMPORTS_ENABLED` and the secret store does not. It reads names only, changes nothing, and treats
anything it cannot read as a failure.

**Layer 6b** adds the validation engine that compares the declaration to the secret store and the
apps, and the code-owned-by-configuration list of activatable environments
(`activation.activatable_environments`, shipped empty): see "Promotion tooling" below. The drift
script remains the deploy-time refusal; the engine is what the promotion gate and
`python -m promotion activation <env>` run.

### Test environments

Nothing generated reads the declaration at runtime. The suites that exercise imports switch the
setting on themselves, in their own disposable process: the unit and integration suites set
`imports_enabled` on the API settings or the worker's `imports` object, the worker-image test passes
`IMPORTS_ENABLED=true` to its container (and also drives the image's tasks with it off), and the
Playwright round trip sets it in the env of the disposable API it starts (`playwright.config.ts`).
No `.env`, compose file or committed config ships a default of on (a test scans for it).

### Running the activation suites

`python-packages/koras-import/tests/test_activation.py`, `tests/unit/test_import_activation_gate.py`
and `tests/unit/test_import_activation_declaration.py` need nothing; the generator-integration
workflow runs them by name and fails on any skip. The image test needs Docker, a PostgreSQL and a
Redis like the rest of `test_worker_image.py`.

## Promotion tooling (layer 6b)

ADR 0013 sections 7 and 9: the Starter owns the **generic** half of the tooling that decides
whether an environment may be asked to rely on the secure-files chain and, where the product has
it, to activate data import. It is generated with `secure_files` and is **read-only**: nothing in
it enables an environment, writes to a database or a secret store, or prints a secret, an object
key or a file name. A check that cannot establish its answer FAILS; unknown is never a pass.

    PYTHONPATH=tooling uv run python -m promotion gate --env <dev|test|stg|prod> [--commit <sha>] [--out f.json]
    PYTHONPATH=tooling uv run python -m promotion activation <env> [--skip-fly]
    PYTHONPATH=tooling uv run python -m promotion f1 --env <env>
    bash local/scripts/qualify-storage-provider.sh <env>

### What is generic, and what is the product's

| Generic: `tooling/promotion`, owned by the Starter | The product's: configuration, never Starter code |
|---|---|
| the gate and its checks, the strict parsers (configuration, register, declaration, junit, dispositions), the fail-closed rules | `local/config/promotion.yaml`: secret-store project and each environment's config, the deployed apps, the scanner setting, the required CI jobs, the register path and id pattern, the qualification directory and freshness |
| the F1 detector: one read-only transaction, the classes of evidence, the dispositions *format* | `local/config/f1-dispositions.yaml`: the dispositions themselves (ships **empty**; honoured for `dev` only) |
| the provider-qualification harness: the attack matrix, the evidence record and how it is bound | the qualification record for each environment (`local/.qualification/<env>.json`, git-ignored) |
| the security-register parser | `docs/security/SECURITY-REGISTER.md`: the findings (ships empty, with the explicit marker) |
| activation: the comparison of a declaration with what an environment will run | `local/config/import-activation.yaml` (6a) and `activation.activatable_environments`: which environments may ever be enabled (ships **empty**) |
| the two adapters (below) | which adapter, and the names they are called with |

**The adapter boundary.** The engine never calls a vendor CLI. Everything it needs from outside is
one of three reads: a setting's value in an environment's secret store (`SecretStore.get`), the
secret names and machines of a deployed app (`DeployTarget.secrets`, `.machines`), and the check
runs of a commit (`gh api`, in `gate.py`). The Starter ships the two adapters it uses product-wide,
Doppler and Fly, in `adapters.py`; they issue only `doppler secrets get`, `flyctl secrets list` and
`flyctl machines list`, as argument lists with no shell, from names validated against a strict
pattern first (so a value from the configuration can never become an option). A product on another
store or host adds an adapter class and a name to `SECRET_STORES` / `DEPLOY_TARGETS` (and
`config.SUPPORTED_*`); nothing else changes. This is the only place a vendor is named. No Docoris
Fly app, Doppler project or config, finding or F1 disposition exists in the Starter.

### `promotion.yaml`

Strict: an unknown key, a missing key, a wrong type, an app or setting name that could be read as
an option, a path that leaves the repository, a pattern that does not compile and an
`environments` block that is not exactly `dev`, `test`, `stg` and `prod` are all a FAIL of the
`promotion_config` check. There is no default that stands in for a missing declaration. The
`activation` section is rendered only with `data_import`.

### The gate's checks

| Check | Passes when |
|---|---|
| `promotion_config` | the configuration is present and valid |
| `activation_*`, `imports_off` | (`data_import` only) the declaration is exact; every environment declared `disabled` holds **no** `IMPORTS_ENABLED` in the secret store (not even `false`) and on neither the api nor the worker app; an `enabled` environment is listed in `activation.activatable_environments`, resolves to on in the store and has no hand-set copy; api and worker agree. Without `data_import`: `activation_not_applicable`. A checkout that has the declaration or the engine package but whose configuration has no `activation` section is a FAIL, not a skip |
| `scanner_configured`, `scanner_healthy` | the environment's store names the required backend (never `none`, unset or a lookalike) and its scanner app has every machine started with every health check passing |
| `immutable_finalization` | the finalizer, the finalize-first hand-off to the scanner, the incoming-key ticket, the release rule and the generated `SECURE_FILES = True` are present |
| `provider_qualification` | a fresh record for **this** environment's **own** store and **this** code (below) |
| `f1_unverified_releasable` | `F1_UNVERIFIED_RELEASABLE_COUNT = 0` against the environment's own database |
| `ci_suites` | every job in `ci.required_jobs` completed successfully on the commit, reported by GitHub Actions (a check run from another app under a required name is ignored; the latest run of a job wins; one still running fails) |
| `import_gate_installed` | (`data_import` only) the 6a gate is in the router, the worker task and its tests |
| `security_findings` | no unresolved Critical or High finding of type `SECURITY` or `SECURITY-GAP` in the register |

Every collector runs behind a guard, so an unexpected exception is a FAIL that names only the
exception class. The command exits non-zero unless every check passed; `--out` writes the evidence
record, after first replacing any previous one with a FAIL placeholder so a run that does not
finish cannot leave a stale PASS. Gate evidence is a record of one commit on one date; this page
makes no statement about whether any commit currently passes.

The gate is not wired into the product's deploy workflow, because the deploy is the same file with
and without the capability (ADR 0013 section 2). It is its own workflow,
`.github/workflows/promotion-gate.yml` (`workflow_dispatch`, and `workflow_call` so an
environment's deploy workflow can `needs:` it), with `contents: read` and `checks: read` only. It
cannot run the provider qualification (which needs a disposable local database and writes into the
target bucket), so in CI the `provider_qualification` check reports the absence of a record.

### The F1 detector

A *releasable* row is whatever `RELEASABLE_SQL` selects, asked again of the Python `releasable()`;
a disagreement raises. Each one must carry **verified-digest evidence**:
`checksum_verified_at` is set (its only writers are the upload finalizer's swap, after it hashed
the incoming and the final bytes to the claim, and a restore replacement, which hashed what it
wrote), the claim is 64 lower-case hex, the key is this tenant's *and this file's* final key, and
the verdict (`scan_attempted_at`) is not older than the verification beyond 60 s of clock skew.
Everything else is counted in a failing class (`final_key_no_verified_digest`,
`verdict_predates_verification`, `missing_claim`, `legacy_key_releasable`,
`incoming_key_releasable`, `unrecognised_key_shape`). Read-only by construction: `begin transaction
read only`, a check that the server says it is, `select` statements only (a unit test scans them),
`rollback`. It refuses a role that does not bypass row-level security (every count would read zero
and prove nothing). Run standalone it reads the admin URL from the process environment and refuses
one that the secret store's own runner did not bind to `--env` (`doppler run --config <env> -- ...`;
`--allow-unbound` is the explicit override); inside the gate it reads that environment's own admin
URL from the secret store, so it cannot be pointed at another environment's database. Output names
tenant ids, file ids and a class, never a key or a name. Pending,
infected, skipped and identity-failing rows are reported apart and never counted. A disposition
silences one `tenant:file` for one recorded class and is honoured only for `dev`; the raw and the
net count are always both printed. The remediation classes of the product this was proven in (a
legacy re-trust and an overwrite-restore key shape) are not in the Starter: it has neither.

### Provider qualification, and what its record is bound to

`qualify-storage-provider.sh <env>` runs the upload attack matrix (`test_upload_checksum_provider`,
`test_upload_finalization_provider` and `test_provider_qualification_extra`) against the
environment's **own** store, with disposable objects under random tenant prefixes, and writes a
record only for a run that is clean in the junit file **and** in pytest's exit status (any earlier
record is removed when a run starts). It writes to the target bucket with the target's real
credentials, and needs a disposable local Postgres (`E2E_DATABASE_URL`, loopback only: the shell
script and the Python module both refuse anything else). A required case that is missing, skipped,
errored or failed is a FAIL; an environment with no storage credentials is a FAIL, not a skip.

The record vouches for exactly:

| Bound to | How | A change makes the record stale because |
|---|---|---|
| the store | `storage_fingerprint`: SHA-256 of `endpoint\|bucket\|region` of the environment's *current* secret-store configuration | another environment's record, or the same environment pointed at another bucket, never verifies |
| the code | `guard_hash`: SHA-256 over the line-ending-normalised contents of `GUARD_FILES` (the upload controls, the finalizer and its job, the release rule, the files router, this module and the three suites) | any edit to any of them |
| the harness | `harness_version` (an integer, bumped when a case is added, removed or changes what it asserts) and the exact set of required cases | a record with another version, or whose cases are not exactly the required ones, fails |
| the date | `created_at`, fresh for `qualification.max_age_days` (14 by default), not future-dated, with a timezone | age |

The record holds no secret, key or file name. `--credentials process` runs the matrix against a
disposable local S3-compatible store whose settings are in the process environment (this is how the
suites are run against MinIO); the record then names that store's fingerprint and verifies for no
environment whose configured store differs.

### The forged-provenance regression (ADR 0013 section 9)

**What already existed.** The Layer 2 suites cover provenance that is *absent*: `test_D_...` D2 and
D3 copy from a victim object that carries no provenance metadata, so what lands carries none (D2
asserts only `!=` the ticket's id); and `INJECTED["forged-provenance"]` sends a forged header on a
*guarded* ticket, where the provider refuses and nothing lands. Neither puts a forged,
**non-empty** provenance on an object that *landed*.

**What the harness adds**, as required case `m12_forged_nonempty_provenance` (matrix row 12), in
`tests/integration/test_provider_qualification_extra.py::test_Q13_...`. With test-only mechanics and
disposable fixtures, and no production guard weakened and no production path created
(`Run.ticket(guarded=False)`, `metadata_only_ticket` and `forged_signed_ticket` exist only in the
suites, and a test asserts that `guarded=False` appears in no production file):

- a victim object carrying its own, non-empty upload id as provenance;
- an intentionally **unguarded** copy-source ticket: the provider copies the victim's bytes *and its
  metadata*, so the object lands with a forged non-empty provenance that is not the ticket's
  identity, and **its bytes hash to the claim**, so the digest checks would pass;
- the same through a ticket that signs the provenance but not the copy preconditions;
- the metadata REPLACEd with a forged string or a sibling ticket's upload id (a provider that
  insists every `x-amz-*` header be signed refuses these and leaves nothing behind, which also
  passes; at least one scenario must land, or the case fails as vacuous);
- the attacker's own bytes, an honest digest and a forged provenance signed into the ticket;
- forged provenance together with a claim the landed bytes do not match (the digest requirement
  still applies independently);
- a positive control: an honest guarded upload is finalized by the same finalizer.

The real `UploadFinalizer` must refuse each one that landed (`held`, `integrity_mismatch`; the row
stays on its incoming key, `pending`, unverified, with no final object), and the victim object is
untouched.

**Mutation check.** With the finalizer's provenance comparison changed from `stored_upload !=
upload_id` to `not stored_upload` (accept any non-empty provenance), applied to a scratch copy of a
generated product and reverted, `test_Q13_...` fails at its first scenario
(`copied_victim_provenance: a forged provenance must be refused`, the finalizer returning
`FINALIZED`), while the Layer 2 provider suites alone (`test_upload_checksum_provider.py` and
`test_upload_finalization_provider.py`, 25 tests) all pass against the same mutant: they could not
have caught it.

**Why earlier records are stale.** The case changes `HARNESS_VERSION` (1 to 2), the three suite
files and `provider_qualification.py` (so `guard_hash`), and the set of required cases. A record
issued before it fails verification on each of those three counts independently
(`test_a_record_issued_before_the_forged_provenance_case_is_stale_on_three_counts`), which is how
Docoris binds its records (`guard_hash` over the same kind of file list) with the version added.

### Running the promotion suites

`tests/unit/test_promotion_*.py` need nothing (and `test_promotion_activation.py` exists only with
`data_import`). `tests/integration/test_f1_detector_real.py` needs a migrated PostgreSQL as a role
that bypasses row-level security (`E2E_ADMIN_DATABASE_URL`) and the restricted application role
(`E2E_DATABASE_URL`). `tests/integration/test_provider_qualification_extra.py` needs the same
database and an S3-compatible store (`STORAGE_*`). The generator-integration workflow runs the unit
suites by name and the real ones in the secure-files row, and fails on any skip.

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
| 4 | `services/api/koras_api/core/file_release.py` | always | the one rule: `releasable`, `RELEASABLE_SQL`, `refusal_reason`; dispatches on `SECURE_FILES`; standard library plus `secure_files` only, so the worker image carries it |
| 4 | `services/api/koras_api/core/file_release_gate.py` | capability | the API-only gate: `require_releasable` (a request), `read_releasable` (a process that reads the object), `row_releasable` (one place a row's columns become the rule's arguments) |
| 4 | `services/api/koras_api/core/release_audit.py` | capability | the `storage.object.release_refused` action the gate records |
| 4 | `services/api/koras_api/core/errors.py` | rendered by the capability | `FILE_SCAN_PENDING` (409): no clean verdict for this exact object |
| 4 | `services/api/koras_api/routers/files.py` | rendered by the capability | download through the gate; the list's `content_available` and the hook offer; completion signs nothing (the legacy half asks the same rule) |
| 4 | `services/api/koras_api/core/file_hooks.py`, `core/file_indexing.py` | rendered by the capability | `after_clean`/`due` in place of `after_upload`; the assistant's hook |
| 4 | `services/api/koras_api/core/ai.py`, `core/knowledge.py`, `ai/tools.py` | rendered by the capability (`ai`) | `index_clean_file`, the guarded chunk writer and its read identity, the gated retrieval statement, the conversation replay filter, `content_available` in the file tool |
| 4 | `services/api/koras_api/core/imports.py` | rendered by the capability (`data_import`) | the import source asks the rule; no deny-list |
| 4 | `services/worker/Dockerfile` | rendered by the capability | copies `file_release.py` and `secure_files.py` (the import gate in the worker's copy of `core/imports.py` asks the rule); the audit sink and rebind are copied once, not twice, when `data_import` is on |
| 4 | `supabase/migrations/00042_file_derived_content_withdrawal.sql` | capability | the withdrawal triggers; Docoris 01019 |
| 4 | `supabase/tests/360_file_derived_content_withdrawal.sql` | capability | the triggers, the read gate's predicate (including an incoming key and an unstamped row) and tenant isolation under forced row-level security, as the restricted role; without the assistant it proves what remains |
| 4 | `packages/api-client/src/file-state.ts` (+ `.test.ts`) | capability | the Files page's closed reading of what the server released: `available`, `scanning`, `unavailable`, the refresh delays and the deadline |
| 4 | `apps/web/src/app/dashboard/files/{FilesPanel,page,actions}` | rendered by the capability | the status column, the disabled Download, the bounded refresh and the neutral notice on a stale page; the sentences are in the three catalogues of every product |
| 4 | `tests/unit/test_file_release.py`, `test_files_release_api.py`, `test_release_bypass_guards.py`, `release_support.py` | always, per mode | the rule in both modes (the same row decided both ways), the routes in whichever mode was generated, the static guard of every consumer |
| 4 | `tests/unit/test_files_lazy_indexing_api.py`, `test_ai_indexing_gate.py`, `test_derived_content_withdrawal_static.py` | capability | the list's offer, the indexer's gate, the migration's shape |
| 4 | `tests/integration/test_file_release_real.py`, `test_file_derived_content_real.py` | capability | the rule's two spellings over every state, identity and tenant isolation, the withdrawal against a real PostgreSQL with the scanner's own transitions and a racing index write |
| 4 | `tests/integration/test_release_orchestration_real.py` | capability | release end to end against a real PostgreSQL, store and clamd: refused until clean, then the signed URL serves the uploaded bytes; EICAR is quarantined; a late infected verdict stops release; another tenant's real clean object never releases through a row of this tenant; run in the scanner step with those three |
| 4 | `tests/integration/test_worker_image_scanner.py` | capability | gains one test: the image carries the release rule exactly where the import gate asks for it (with `data_import`), never the API-only gate |
| 4 | `tests/integration/test_import_commit_atomic.py`, `test_import_commit_rls.py`, `worker_image_probe.py` | rendered by the capability (`data_import`) | the fixture file is a releasable one (a clean verdict on a final key of its tenant, stamped), as the import gate now requires; without the capability it is what it was |
| 4 | `tests/integration/test_worker_image.py` | always (`data_import`) | a product with the capability gives the image's worker the scanner and store settings it refuses to start without (an import reads neither) |
| 4 | `e2e/roundtrip/files-release-state.spec.ts` | capability | the Files page in a browser against the real API, the real rule and row-level security |
| 4 | generator: `tests/product-secure-files-release.test.ts` | Starter only | both modes rendered; each half asserted from the generated text |
| 5 | `services/worker/koras_worker/tasks/storage_restore.py` | always, rendered by the capability (`storage_governance`) | the restore worker: the replacement as a new final-shaped object, verified and read back, the row switched and reset in one statement; the legacy text is what it was without the capability |
| 5 | `services/worker/koras_worker/tasks/restore_scan.py` | capability + `storage_governance` | asking the scanner about what a restore wrote, and the follow-up for a lost request; an enqueuer and a reader only |
| 5 | `services/api/koras_api/core/upload_window.py` | capability | `final_key(...)`: the key a server-side writer other than the finalizer makes, in the one shape `is_final_key` accepts |
| 5 | `services/api/koras_api/core/scan_enqueue.py` | capability | `enqueue_scan(..., delay_seconds=None)`: the one enqueue function, deferrable for a new row |
| 5 | `tests/unit/test_release_bypass_guards.py` | always, per mode | the bypass guard's writer registry holds the restore writer (`'pending'` only); `scan_status` is found in the restore in a secure product and not in a legacy one |
| 5 | `tests/unit/test_scan_task.py` | capability | the guard on who may name the scan task lists `restore_scan.py` where it exists |
| 5 | `tests/unit/test_storage_restore.py` | always (`storage_governance`), rendered | the legacy assertions, and the secure rendering's `Ran` result |
| 5 | `tests/unit/restore_support.py`, `test_storage_restore_replacement.py`, `test_restore_scan.py` | capability + `storage_governance` | the decision, the key shape, the verified write, the statements' text, the request arithmetic and the enqueuer-only guards |
| 5 | `tests/unit/test_upload_finalization.py`, `test_scan_enqueue.py` | capability | `final_key` and the deferrable enqueue |
| 5 | `tests/integration/test_restore_replacement_real.py` | capability + `storage_governance` | the replacement against a real PostgreSQL with RLS forced: new key, reset evidence, refusals write nothing, races with the scanner's own transitions, ambiguous commits, tenants |
| 5 | `tests/integration/test_restore_derived_content_real.py` | capability + `storage_governance` + `ai` | the chunks withdrawn with the replacement, and an index write racing a restore |
| 5 | `tests/integration/test_restore_orchestration_real.py` | capability + `storage_governance` | the restore end to end against a real database, store and clamd: refused until a fresh clean verdict, a stale URL reads old bytes only, infected restored bytes are quarantined, a quarantined file returns only as a new scanned file |
| 5 | `tests/integration/test_worker_image_scanner.py` | capability | gains one test: the restore modules load in the image and a replacement key it makes is a final key |
| 5 | `docs/SECURE_FILES.md` (product) | capability | the operator's "Restoring a file" section, with `storage_governance` |
| 5 | generator: `tests/product-secure-files-restore.test.ts` | Starter only | both modes rendered; the legacy rendering equals the previous one; with and without `storage_governance` |
| 6a | `python-packages/koras-import/src/koras_import/activation.py`, `tests/test_activation.py` | `data_import` | `parse_import_activation`, `ACTIVATION_ON`, `IMPORTS_ENABLED_SETTING`: the one parse rule for both processes |
| 6a | `services/api/koras_api/core/settings.py` | always, rendered | `imports_enabled: bool = False` with a before-validator, only with `data_import` |
| 6a | `services/api/koras_api/routers/imports.py`, `core/errors.py` | `data_import` / always | `require_import_activation` on the router; `ApiErrorCode.IMPORT_NOT_ENABLED` |
| 6a | `services/worker/koras_worker/tasks/imports.py` | `data_import` | `ImportSettings.imports_enabled` and `_refuse_while_disabled`, first in both tasks |
| 6a | `local/config/import-activation.yaml` | `data_import` | the per-environment declaration, every environment `disabled` |
| 6a | `local/scripts/import-activation-drift.sh` | `data_import` | the deploy-time drift refusal (app holds the setting, secret store does not) |
| 6a | `local/config/secrets.manifest` | always, rendered | `IMPORTS_ENABLED optional - bool`, only with `data_import` |
| 6a | `.github/workflows/deploy.yml` | always | a step that runs the drift script when the declaration exists |
| 6a | `playwright.config.ts` | always, rendered | `IMPORTS_ENABLED: 'true'` in the round-trip API's env, only with `data_import` |
| 6a | `tests/unit/test_import_activation_gate.py`, `test_import_activation_declaration.py` | `data_import` | both gate states in the API and the worker, enqueue-bypass guards, declaration schema |
| 6a | existing import suites (`test_import_inspection.py`, `test_import_templates_api.py`, `test_import_worker_envelope.py`, `test_worker_heavy_sections.py`, `test_import_commit_*`, `test_worker_image.py` + probe) | `data_import` | open the gate for themselves; the image probe also runs both tasks with it off |
| 6a | `apps/web/src/lib/api-errors.ts`, `packages/i18n` (en, de, es) | always | `errors.importNotEnabled` |
| 6a | generator: `tests/product-import-activation.test.ts` | Starter only | declaration, gate and manifest present with `data_import`, absent without; every environment ships `disabled` |
| 6b | `tooling/promotion/{__init__,__main__,result,config,adapters,register,activation,f1,provider_qualification,gate}.py` | capability | the generic, read-only promotion tooling: strict configuration, the two adapters (Doppler, Fly), the strict register parser, activation validation, the F1 detector, the provider-qualification harness and the promotion gate |
| 6b | `local/config/promotion.yaml` | rendered by the capability (`activation` section with `data_import`) | the product's declaration: secret-store project and configs, deployed apps, scanner setting, CI jobs, register, qualification directory and freshness, activatable environments (empty) |
| 6b | `local/config/f1-dispositions.yaml` | capability | the dispositions format; ships empty (honoured for `dev` only) |
| 6b | `docs/security/SECURITY-REGISTER.md` | capability | the register the gate reads; ships with the header and the explicit empty marker |
| 6b | `local/scripts/qualify-storage-provider.sh`, `local/.qualification/.gitignore` | capability | the qualification entry point (loopback database only) and the git-ignored record directory |
| 6b | `.github/workflows/promotion-gate.yml` | capability | the gate as its own `workflow_dispatch` / `workflow_call` workflow, read-only; the deploy workflow is not changed |
| 6b | `tests/integration/test_provider_qualification_extra.py` | capability | matrix rows 4 and the download-URL invariant stated on their own, and **row 12, the forged-provenance regression** (ADR 0013 section 9), against a real S3-compatible store and the real finalizer |
| 6b | `tests/unit/promotion_support.py`, `test_promotion_{config,adapters,register,f1,gate,provider_qualification}.py` | capability | the configuration, the adapters (read-only allowlist), the register parser (negative cases and a seeded fuzz), the F1 classes and dispositions, the gate decided from a table (every missing, invalid or stale piece of evidence in every environment), the qualification evidence binding |
| 6b | `tests/unit/test_promotion_activation.py` | capability + `data_import` | absent means off, drift, api/worker agreement, the declaration alone never activates, the declaration's schema |
| 6b | `tests/integration/test_f1_detector_real.py` | capability | the detector against a real PostgreSQL as a BYPASSRLS role: every class, both tenants, the application role refused, read-only, nothing changed |
| 6b | `pyproject.toml` | always, rendered | `pythonpath` gains `tooling`, only with the capability |
| 6b | `.github/workflows/generator-integration.yml` | Starter only | steps that run the promotion suites in the secure-files row and fail on any skip |
| 6b | generator: `tests/product-secure-files-promotion.test.ts` | Starter only | files in which mode, the rendered configuration agrees with the generated CI and secrets manifest, nothing of another product, the deploy workflow unchanged, the guard list and the required tests exist |

**EICAR.** No generated file contains the literal test string (every antivirus that reads a
repository may quarantine it): `tests/unit/eicar_support.py` holds it base64-encoded and
`materialize()` decodes it, checked against its recorded SHA-256, on every call.

Migrations: 00039 (layer 2), 00040 and 00041 (layer 3), 00042 (layer 4); layer 5 adds none (Docoris's
restore migration and RLS suite are the Starter's own, byte for byte). New ones take the next numbers and
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