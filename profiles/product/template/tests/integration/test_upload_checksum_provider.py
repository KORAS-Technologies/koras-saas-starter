# ruff: noqa: ANN001, ANN201, ANN003, ANN202, ANN401, E501, S101, E402, S310, S324, F401, F811
"""The provider attack matrix, against a real object store (ADR 0013, `secure_files`).

A signed PUT does not confine what lands on its key: a provider honours an *unsigned*
`x-amz-copy-source` header and turns the PUT into a server-side copy from any key in the bucket.
This suite replays that attack and the product's answer to it, with real signed URLs, real HTTP,
the real `S3ObjectStore`, the real finalizer and its job, and a real PostgreSQL row:

    A  ordinary upload with the correct checksum                       -> finalized
    B  ordinary upload with a wrong checksum                           -> held
    C  copy-source from a victim + the attacker's own checksum         -> held
    D  copy-source from a victim + the VICTIM's checksum               -> never releasable
    E  same-length altered body                                        -> held
    I  unsigned provider-specific headers added to a guarded ticket    -> nothing lands

(F delayed PUT, G re-aimed PUT and H unsigned PUT are `test_upload_finalization_provider.py`, run
with the same real signed tickets.) The *guarded* ticket is what the API issues. Several cases
also run against a ticket with the guard removed or reduced, to model a provider that does not
honour it, because the product's own promotion check must hold without the guard.

The forged-provenance cases (D2 and D3) are the ADR 0013 section 9 regression: a copy-source
ticket is intentionally left unguarded, the copied provenance is not the ticket's upload id, and
finalization must still refuse because provenance is not the expected upload identity. No
production guard is weakened to build it: the unguarded ticket exists only inside this test.

Disposable objects only: every attacker key is under `tenants/<a random tenant>/`, the victim
object is under its own random tenant prefix, no row but the seeded one exists, and everything is
deleted at the end with both prefixes listed to prove them empty. Prints no credential.
"""

from __future__ import annotations

import hashlib
import urllib.parse
import uuid

import pytest
from koras_api.core.upload_window import incoming_key, is_incoming_key
from koras_storage import UPLOAD_PROVENANCE_META, upload_guard_headers
from koras_worker.uploads.finalize import FinalizeKind
from test_upload_finalization_provider import (
    NOW,
    A,
    B,
    Run,
    _finalize,
    _job,
    _row,
    _seed,
    engine,
    pytestmark,
    run,
)

VICTIM = b"VICTIM,SECRET\ntenant-b,4242,confidential\n" + uuid.uuid4().hex.encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def releasable(*, status: str, scan_status: str, storage_key: str) -> bool:
    """The most this layer can say: a file is never releasable while it is unverified or on a
    key a ticket could write. The release rule proper is a later layer's; this is its floor."""
    return status == "ready" and scan_status == "clean" and not is_incoming_key(storage_key)


@pytest.fixture
def victim(run: Run):
    """Another tenant's final object, known by its key, in the same bucket."""
    other = str(uuid.uuid4())
    key = f"tenants/{other}/documents/{uuid.uuid4()}/final/{uuid.uuid4()}/secret.csv"
    run.client.put_object(Bucket=run.bucket, Key=key, Body=VICTIM, ContentType="text/csv")
    try:
        yield key
    finally:
        run.store.delete(key)
        left = run.client.list_objects_v2(Bucket=run.bucket, Prefix=f"tenants/{other}/")
        assert left.get("KeyCount", 0) == 0, "the victim object was not cleaned up"


def copy_headers(run: Run, victim_key: str) -> dict[str, str]:
    return {"x-amz-copy-source": f"/{run.bucket}/{victim_key}"}


def metadata_only_ticket(run: Run, file_id: str, size: int, claim: bytes) -> tuple[str, str]:
    """A ticket that signs the provenance metadata but NOT the copy-source preconditions.

    Isolates the product's second control: if the provider executed the copy anyway, the object
    would carry the source's metadata, not this ticket's upload id.
    """
    upload_id = str(uuid.uuid4())
    key = incoming_key(run.tenant, "documents", file_id, upload_id, "a.csv")
    guards = upload_guard_headers(upload_id)
    only = {
        n: v
        for n, v in guards.items()
        if n in {"x-amz-metadata-directive", f"x-amz-meta-{UPLOAD_PROVENANCE_META}"}
    }

    def hook(request, **_kw: object):
        for name, value in only.items():
            request.headers.add_header(name, value)

    run.client.meta.events.register("before-sign.s3.PutObject", hook, unique_id="secure-files-meta-only")
    try:
        url = run.store.presign_upload(key, "text/csv", size, 600, sha(claim), provenance=None)
    finally:
        run.client.meta.events.unregister("before-sign.s3.PutObject", unique_id="secure-files-meta-only")
    import base64

    run.headers[url] = {
        "Content-Type": "text/csv",
        "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha(claim))).decode(),
        **only,
    }
    return key, url


async def _assert_not_releasable(engine, run: Run, file_id: str, incoming: str) -> dict:
    row = await _row(engine, run, file_id)
    assert row["storage_key"] == incoming, "the row was never moved to a final key"
    assert row["scan_status"] == "pending" and row["checksum_verified_at"] is None
    assert not releasable(**{k: row[k] for k in ("status", "scan_status", "storage_key")})
    assert not [k for k in run.keys() if "/final/" in k], "no final object was left behind"
    return row


# --- A ------------------------------------------------------------------------------------------


async def test_A_an_ordinary_upload_with_the_correct_checksum_is_promoted_and_job(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A), claim=A)
    assert run.put(url, A) == 200
    assert run.client.head_object(Bucket=run.bucket, Key=key)["Metadata"] == {
        UPLOAD_PROVENANCE_META: key.split("/")[5]
    }, "a plain PUT stores the ticket's own upload id"
    await _seed(engine, run, file_id, key, len(A), claim=A)
    job = await _job(engine, run, file_id)
    assert job["status"] == "finalized"
    row = await _row(engine, run, file_id)
    assert not is_incoming_key(row["storage_key"]) and row["checksum_verified_at"] is not None
    assert run.get(row["storage_key"]) == A


# --- B ------------------------------------------------------------------------------------------


async def test_B_a_wrong_checksum_is_withheld_whether_or_not_the_provider_enforces_it(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    # B1: the ticket signs the wrong digest. A provider that enforces it refuses the PUT; one that
    # does not stores the object. The product's outcome must be the same.
    key, url = run.ticket(file_id, len(A), claim=B)
    status = run.put(url, A)
    print(f"EVIDENCE B1_wrong_signed_checksum_put_status={status}")
    await _seed(engine, run, file_id, key, len(A), claim=B)
    job = await _job(engine, run, file_id)
    assert job["status"] == "held"
    assert job["failure"] in {"integrity_mismatch", "object_unreachable"}
    await _assert_not_releasable(engine, run, file_id, key)

    # B2: no digest signed at all (the provider enforces nothing) and the row claims B.
    file_2 = str(uuid.uuid4())
    key_2, url_2 = run.ticket(file_2, len(A))
    assert run.put(url_2, A) == 200
    await _seed(engine, run, file_2, key_2, len(A), claim=B)
    job_2 = await _job(engine, run, file_2)
    assert job_2["status"] == "held"
    assert job_2["failure"] == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_2, key_2)


# --- C ------------------------------------------------------------------------------------------


async def test_C_a_copy_from_a_victim_with_the_attackers_own_checksum_is_withheld(
    engine, run, victim
) -> None:
    # C1: the guarded ticket the API issues. The provider answers the copy with 412 and writes nothing.
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(VICTIM), claim=A)
    status = run.put(url, b"X" * len(VICTIM), extra=copy_headers(run, victim))
    print(f"EVIDENCE C1_guarded_copy_status={status}")
    assert status in {403, 412}
    assert run.keys() == [], "the copy created no incoming object at all"
    await _seed(engine, run, file_id, key, len(VICTIM), claim=A)
    job = await _job(engine, run, file_id)
    assert job["status"] == "held"
    assert job["failure"] == "object_unreachable"
    await _assert_not_releasable(engine, run, file_id, key)

    # C2: an unguarded ticket (the provider honours the copy). The victim's bytes land, and the
    # attacker's claim cannot match them.
    file_2 = str(uuid.uuid4())
    key_2, url_2 = run.ticket(file_2, len(VICTIM), guarded=False)
    status_2 = run.put(url_2, b"X" * len(VICTIM), extra=copy_headers(run, victim))
    print(f"EVIDENCE C2_unguarded_copy_status={status_2}")
    assert status_2 == 200 and run.get(key_2) == VICTIM, "the attack the guard exists to stop"
    await _seed(engine, run, file_2, key_2, len(VICTIM), claim=A)
    job_2 = await _job(engine, run, file_2)
    assert job_2["status"] == "held"
    assert job_2["failure"] == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_2, key_2)
    assert VICTIM not in [run.get(k) for k in run.keys() if "/final/" in k]


# --- D ------------------------------------------------------------------------------------------


async def test_D_a_copy_from_a_victim_with_the_victims_own_checksum_never_becomes_releasable(
    engine, run, victim
) -> None:
    # D1: the guarded ticket the API issues, claiming the victim's digest. Refused at the provider.
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(VICTIM), claim=VICTIM)
    status = run.put(url, b"X" * len(VICTIM), extra=copy_headers(run, victim))
    print(f"EVIDENCE D1_guarded_copy_victim_checksum_status={status}")
    assert status in {403, 412}
    assert run.keys() == []
    await _seed(engine, run, file_id, key, len(VICTIM), claim=VICTIM)
    job = await _job(engine, run, file_id)
    assert job["status"] == "held"
    await _assert_not_releasable(engine, run, file_id, key)

    # D2: copy preconditions NOT signed, provenance metadata signed. The provider executes the copy
    # (the bytes DO match the claimed digest), and what refuses is the missing provenance.
    file_2 = str(uuid.uuid4())
    key_2, url_2 = metadata_only_ticket(run, file_2, len(VICTIM), VICTIM)
    status_2 = run.put(url_2, b"X" * len(VICTIM), extra=copy_headers(run, victim))
    print(f"EVIDENCE D2_metadata_only_copy_status={status_2}")
    assert status_2 == 200, "this ticket has no copy preconditions, so the provider copies"
    assert run.get(key_2) == VICTIM and sha(run.get(key_2)) == sha(VICTIM)
    metadata = run.client.head_object(Bucket=run.bucket, Key=key_2)["Metadata"]
    print(f"EVIDENCE D2_copied_object_metadata={metadata}")
    assert metadata.get(UPLOAD_PROVENANCE_META) != key_2.split("/")[5]
    await _seed(engine, run, file_2, key_2, len(VICTIM), claim=VICTIM)
    job_2 = await _job(engine, run, file_2)
    assert job_2["status"] == "held"
    assert job_2["failure"] == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_2, key_2)

    # D3: no guard of any kind. The incoming bytes hash to the claim, so the hash alone would
    # promote them: this is the answer to "does knowing the victim's key and digest change
    # anything?" -- yes for the hash check, and no for the product, because the object has no
    # provenance of a plain PUT of this ticket.
    file_3 = str(uuid.uuid4())
    key_3, url_3 = run.ticket(file_3, len(VICTIM), guarded=False)
    assert run.put(url_3, b"X" * len(VICTIM), extra=copy_headers(run, victim)) == 200
    assert sha(run.get(key_3)) == sha(VICTIM), "the claim and the copied bytes agree"
    await _seed(engine, run, file_3, key_3, len(VICTIM), claim=VICTIM)
    outcome = await _finalize(engine, run, file_3)
    assert outcome.kind is FinalizeKind.HELD and outcome.failure is not None
    assert outcome.failure.value == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_3, key_3)


# --- E ------------------------------------------------------------------------------------------


async def test_E_an_altered_body_of_the_same_length_is_withheld(engine, run) -> None:
    file_id = str(uuid.uuid4())
    # E1: no digest signed (nothing at the provider can notice), row claims the honest bytes.
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200
    assert run.put(url, B) == 200, "the same ticket, reused: same length, different bytes"
    await _seed(engine, run, file_id, key, len(A), claim=A)
    job = await _job(engine, run, file_id)
    assert job["status"] == "held"
    assert job["failure"] == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_id, key)

    # E2: with the digest signed, a provider that enforces it refuses the altered body (recorded,
    # not relied on).
    file_2 = str(uuid.uuid4())
    key_2, url_2 = run.ticket(file_2, len(A), claim=A)
    status = run.put(url_2, B)
    print(f"EVIDENCE E2_altered_body_with_signed_checksum_status={status}")
    assert status != 200 or run.get(key_2) != A


# --- I ------------------------------------------------------------------------------------------


INJECTED = {
    "if-none-match": {"x-amz-copy-source-if-none-match": '"1"'},
    "if-modified-since": {"x-amz-copy-source-if-modified-since": "Thu, 01 Jan 1970 00:00:00 GMT"},
    "metadata-replace": {"x-amz-metadata-directive": "REPLACE"},
    "forged-provenance": {f"x-amz-meta-{UPLOAD_PROVENANCE_META}": "forged"},
    "tagging-replace": {"x-amz-tagging-directive": "REPLACE"},
    "checksum-algorithm": {"x-amz-checksum-algorithm": "SHA256"},
    "copy-range": {"x-amz-copy-source-range": "bytes=0-5"},
    "storage-class": {"x-amz-storage-class": "STANDARD"},
    "acl": {"x-amz-acl": "public-read"},
    "second-if-match": {"x-amz-copy-source-if-match": '"11111111111111111111111111111111"'},
    "all-at-once": {
        "x-amz-copy-source-if-none-match": '"1"',
        "x-amz-copy-source-if-modified-since": "Thu, 01 Jan 1970 00:00:00 GMT",
        "x-amz-metadata-directive": "REPLACE",
        "x-amz-tagging-directive": "REPLACE",
    },
}


@pytest.mark.parametrize("name", sorted(INJECTED))
async def test_I_unsigned_provider_headers_cannot_turn_a_guarded_put_into_a_copy(
    engine, run, victim, name
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(VICTIM), claim=VICTIM)
    status = run.put(url, b"X" * len(VICTIM), extra={**copy_headers(run, victim), **INJECTED[name]})
    print(f"EVIDENCE I_{name}_status={status}")
    assert status in {400, 403, 412}
    assert run.keys() == [], "nothing landed on the incoming key"
    assert run.get(victim) == VICTIM


async def test_I_dropping_the_signed_guard_headers_is_refused(engine, run, victim) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(VICTIM), claim=VICTIM)
    status = run.put(
        url,
        b"X" * len(VICTIM),
        only={"Content-Type": "text/csv"},
        extra=copy_headers(run, victim),
    )
    print(f"EVIDENCE I_dropped_guards_status={status}")
    assert status in {400, 403}
    assert run.keys() == []


async def test_I_a_guarded_ticket_still_accepts_the_ordinary_upload_with_every_header_sent(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A), claim=A)
    assert set(upload_guard_headers("x")) <= set(run.headers[url]) | {
        f"x-amz-meta-{UPLOAD_PROVENANCE_META}"
    }
    assert run.put(url, A) == 200 and run.get(key) == A
