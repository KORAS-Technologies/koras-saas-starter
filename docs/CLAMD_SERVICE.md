# The clamd service

> Scope: the optional private malware scanner a generated product can carry —
> ClamAV's `clamd`, in `services/clamd/`. Shipped 2026-10-03 as the Starter half
> of Docoris OD-12. **This is the scanner and nothing that uses it**: no product
> calls it, no file state is mapped from its answers, and no vendor decision is
> made here (OD-10 stays open).

## What a product gets

`--with clamd`. Off by default and implied by nothing; a product generated
without it is byte-identical to before, apart from the shared deploy and
Terraform machinery ([`SERVICE_DESCRIPTORS.md`](SERVICE_DESCRIPTORS.md)).

```
services/clamd/
  Dockerfile        pinned official image + three files, unprivileged, tini as PID 1
  clamd.conf        every limit, with its derivation
  freshclam.conf    signature updates
  entrypoint.sh     when the scanner may say it is ready
  fly.toml          private, shared-cpu-2x, 2 GiB, TCP check, restart policy
  service.yaml      dev only, no secrets, network private
```

The Fly app is `<product>-clamd-<environment>` — `docoris-clamd-dev` for Docoris.
It exists in `dev` only; the descriptor says so and both Terraform and the deploy
workflow read it. Adding `test`, `stg` or `prod` is an edit to that file.

The generated `pyproject.toml` excludes `services/clamd` from the uv workspace
(only when clamd is on). It is not a Python package, and uv refuses a workspace
glob match with no manifest — `uv lock` failed outright on a generated clamd
product until this was found by running it, which nothing in the unit suite
could have done.

## The image

| | |
|---|---|
| Image | `clamav/clamav` — the ClamAV project's own |
| Version | **1.4.6** (ClamAV 1.4 is the project's long-term-support line) |
| Digest | `sha256:57deb108fc4c72778aa83eafbca7bb7153e28c3f57c005afd38d31f16da86f23` — the multi-architecture index |
| Verified | 2026-10-03: the registry's `Docker-Content-Digest` header for `1.4.6` and a pull by that digest agree; Docker Hub's tag listing and the project's release feed (`clamav-1.4.6`, 2026-08-07) name the same version |

Pinned by version **and** digest: a tag can be moved and a digest cannot. Nothing
floats, nothing is secret, and nothing environment-specific is in the image —
it is the same bytes in every product. To bump it, change both together, read
the release notes, and run the image test (below), which is what says whether
the limits still mean what they did.

1.5.4 was also measured on 2026-10-03 and behaved identically on every question
that decided a limit; 1.4 was chosen for the support line, not for a difference.

## Network: private only

`fly.toml` has no `[http_service]` and no `[[services]]` block — either is what
makes Fly allocate a public address — and Terraform has no IP resource. The only
way in is TCP 3310 over Fly's private network at `<app>.internal`. Terraform
publishes no URL for it, and the deploy verifies the claim afterwards: no public
address, machine started, health check passing.

clamd binds **two** addresses, `TCPAddr 0.0.0.0` and `TCPAddr ::`, and both are
needed. `::` is Fly's private network (6PN), which is how product services
connect. `0.0.0.0` is the machine's internal IPv4, which is what Fly's
host-side `clamd_tcp` machine check connects to: not loopback and not 6PN.
clamd sets `IPV6_V6ONLY`, so `::` alone does not answer on IPv4.

This was found twice, from opposite sides. Binding only `::` left the first
readiness probe pinging `127.0.0.1` forever. Fixing the probe and keeping `::`
only then passed every scan on the first deployment to `docoris-clamd-dev` on
2026-10-03 while Fly's own check reported `connect: connection refused` and the
deploy timed out waiting for health, because nothing a test ran was the thing
Fly connects to. Neither address is public: the IPv4 is eth0's internal one, and
with no `[[services]]` block Fly routes nothing from the internet to the port.

Fly's private network spans the **organisation**, not an environment. Any app in
the organisation can connect. That is a private network and not an isolation
boundary, and this does not pretend to be one.

## Resources

`shared-cpu-2x`, 2 GiB, one machine. API and worker sizing are untouched.
Measured under a 2 GiB / 2 CPU Docker limit on 2026-10-03: idle 1.0 GiB; peak
**1.39 GiB** with a 450 MiB-expansion scan and a 100 MiB scan running together
while a signature reload ran; no out-of-memory kill. Two settings make that true
and are not tidiness: `MaxThreads 2`, and `ConcurrentDatabaseReload no` — a
reload otherwise holds two copies of the signature set, which is what takes
2 GiB over. The price is that scans wait during a reload.

## Starting up: when is it ready

`entrypoint.sh` replaces the image's own `/init`, which starts clamd if a database
file exists and calls it done when a socket appears.

1. **A usable database must exist** — `main`, `daily` and `bytecode`, each
   non-empty. The image bundles all three, so a fresh machine always has one.
   Without them: exit 1, `refusing to start`.
2. **An update is attempted at every start**, bounded to 120 s so a hung mirror
   cannot hold the machine out of service.
3. **If the update fails**, the scanner starts on the existing database *only if
   it is fresh*: the `daily` database changed within `CLAMD_MAX_DB_AGE_DAYS` (7).
   It logs `WARNING: signature update failed; continuing on the existing database,
   N day(s) old`. Older than that: exit 1.
4. **clamd starts and binds TCP 3310 only after it has loaded the signatures**, so
   Fly's TCP check cannot pass before step 1 is true.
5. **A detection self-test** then scans the EICAR test string through the daemon
   and must see it detected. The string is assembled at runtime because a file
   containing it is quarantined by every antivirus that reads the repository.
   Only then does it log `ready`.
6. **It stays honest.** The entrypoint exits — and Fly restarts the machine — if
   either daemon dies, or if the database goes older than the limit while
   running. A scanner answering from a months-old database is the failure
   nothing else would notice.

Fly's restart policy is `on-failure`, ten retries, and then the machine stops and
shows as stopped rather than burning cycles.

**What this does not do.** With no volume, every restart begins from the image's
bundled database, then updates. If the pinned image is old and the update path is
broken, the scanner will refuse to start (step 3) — that is the intended failure,
and the remedy is to bump the image.

## Limits, derived from one number

The owner ratified a **100 MiB** supported scan ceiling on 2026-10-03, matching
Docoris's shipped upload default. The scanner is configured from that number, not
for "any file", and a product with a different ceiling changes the numbers here
rather than assuming them. The test recomputes each limit from it.

| Directive | Value | Derivation |
|---|---|---|
| `StreamMaxLength` | 100M | exactly the ceiling. 100 MiB is scanned; one byte more is refused (`INSTREAM size limit exceeded`) — both measured |
| `MaxScanSize` | 500M | 5× the ceiling: total bytes examined per scan, everything unpacked. An ordinary Office document expands a few times; a ceiling-sized archive of compressed media does not expand at all |
| `MaxFileSize` | 500M | **equal to `MaxScanSize` on purpose** — see below |
| `MaxRecursion` | 8 | nesting. Four deep is an Office document in an attachment in an archive; 8 is double, and half the default 17 |
| `MaxFiles` | 5000 | files unpacked from one input. Ordinary Office documents have hundreds of parts; the default is 10000 |
| `MaxScanTime` | 120000 ms | an ordinary scan takes under a second and a 100 MiB random file 2–8 s on the measuring machine; the slowest bounded case, 450 MiB of expansion, took 38–85 s. Exceeding it is itself reported |
| `AlertExceedsMax` | yes | a limit hit is **reported as a detection**, not skipped |
| `AlertEncrypted`, `…Archive`, `…Doc` | yes | an archive or document it cannot open is reported, not passed |

The earlier unratified recommendation of a `400M` decompression limit was not
copied; 500M is 5× a stated ceiling, and 400M was 4× nothing.

### `MaxFileSize` equal to `MaxScanSize`: the finding that decided it

With `MaxFileSize` at the 100 MiB ceiling — the obvious setting — ClamAV 1.4.6
**skipped a ZIP entry larger than that with no alert at all**, even with
`AlertExceedsMax yes`. Measured: a marker 120 MiB into one archive entry was not
found, and a 1 GiB entry of zeros returned `OK`. An attacker needs nothing more
than a large entry.

At `MaxFileSize` equal to `MaxScanSize`, the same inputs behave: a marker 450 MiB
deep is found, and an entry beyond 500M exceeds `MaxScanSize`, which does alert.
The ceiling on what *arrives* is the stream limit, so nothing is lost by raising
this one.

### What each failure reads as

Measured against the real engine (`tests/clamd-image.test.ts`):

| Input | Answer |
|---|---|
| ordinary Office-shaped document | `OK` |
| exactly 100 MiB | `OK` |
| 100 MiB + 1 byte | `INSTREAM size limit exceeded. ERROR` |
| encrypted archive | `Heuristics.Encrypted.Zip FOUND` |
| nested deeper than 8 | `Heuristics.Limits.Exceeded.MaxRecursion FOUND` |
| 6000 files in one archive | `Heuristics.Limits.Exceeded.MaxFiles FOUND` |
| 1 GiB entry, or 600 MiB of expansion | `Heuristics.Limits.Exceeded.MaxScanSize FOUND` |
| scan over the time limit | `Heuristics.Limits.Exceeded.MaxScanTime FOUND` |

**For Docoris (OD-12), which owns the state mapping:** `OK` is the only answer
that may *become a candidate for* `clean`, and it is **not sufficient on its
own** -- see "A known gap" below. Every `FOUND` — including every `Heuristics.*` — and
every `ERROR`, a refused or dropped connection, a timeout and a malformed reply
must become a non-clean, held outcome. The scanner is configured so that limits
and encryption *arrive as `FOUND`*; mapping them is the product's job.

## A known gap, and it is not configurable

ClamAV 1.4.6 **and** 1.5.4 do not unpack a *deflated, streamed, zip64* archive
entry: one written with a data descriptor and a zip64 extra field, as Python's
`ZipFile.open(..., force_zip64=True)` does. Measured: a marker in such an entry,
a few hundred bytes in, returned `OK`, while the same content in an ordinary
archive was found. No limit reaches it; the entry is simply not inspected.

So **"incompletely inspected content never reads as clean" holds for every
limit and for encryption, and does not hold for this entry form.** Neither this
service nor ClamAV can guarantee complete inspection of that form, and this
document does not claim that ClamAV fully inspects every archive it accepts.
**A product must not treat the affected `OK` as sufficient for release to
`clean`.** The scanner's `OK` is a *candidate-clean* answer; a supported
container (ZIP and the ZIP-derived formats, DOCX and XLSX among them) must also
pass the product's own bounded structural-safety check before it is `clean`.

Owner decision D1, ratified 2026-10-03, for Phase 1 of the product policy:
`FOUND` is infected; an explicit encrypted, incomplete or limit result is held;
a streamed, deflated zip64 entry is held pending, never `clean`, never
`infected` on structure alone, never `skipped`. Customer files are not
modified or repacked, here or by the product. That check belongs to the product
(Docoris OD-12), not to this service.

`tests/clamd-image.test.ts` pins the behaviour as a tripwire. The day the engine
starts finding the marker, that test fails -- and that is a prompt for an
explicit review of the product's structural gate, not an instruction to remove
it. This section is amended by that review, not deleted by the test failing.

## Tests

| File | What it proves | How |
|---|---|---|
| `tests/clamd-service.test.ts` | the contract: pinned image, derived limits, exposure; and the entrypoint's decisions (ready, refuse, stale, self-test, daemon death) | reads the files; **runs** the entrypoint against stand-in daemons that fail on demand. Four mutations were checked: each breaks exactly the test that names it |
| `tests/clamd-image.test.ts` | every measurement above, against the real image under 2 GiB / 2 CPUs | **opt-in**: `KORAS_CLAMD_IMAGE_TEST=1`; needs Docker; minutes |
| `tests/product-clamd.test.ts` | a product without clamd is unchanged; with it, exactly the right files; deterministic; drift and refresh; Terraform exposure; the workflow names no service | renders and compares |
| `tests/service-descriptor-parity.test.ts` | the workflow and Terraform agree, over 45 descriptors | **runs both** |
| `tests/service-secrets.test.ts`, `tests/private-service-verify.test.ts` | the secret policy and the private-service checks | run the real scripts against a `doppler` and `flyctl` that cannot reach anything |

## Not done, and why

Recorded 2026-10-03 rather than left to be rediscovered.

- **Nothing was provisioned, deployed or run live.** The image was built and run
  locally; no Fly app, no Terraform apply, no machine. Whether Fly accepts the
  `[checks]` and `[[restart]]` blocks as written, and whether `grace_period`
  of 180 s is enough on a real `shared-cpu-2x`, is unconfirmed until the first
  deploy. The measuring machine is not a Fly machine and its timings are not
  Fly's.
- **No consumer.** Calling the scanner, the client, the timeout, the state
  mapping and the fail-closed behaviour for oversized files are OD-12.
- **The control plane's registry** has not been asked whether it accepts a
  service key it has not seen before; clamd is off by default and registers
  nowhere unless a product enables it.
- **`none` and `allowlist` do not clear existing secrets** — see
  [`SERVICE_DESCRIPTORS.md`](SERVICE_DESCRIPTORS.md). Deliberate.
