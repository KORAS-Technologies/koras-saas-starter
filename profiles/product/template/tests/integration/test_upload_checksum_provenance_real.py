# ruff: noqa: ANN001, ANN201, ANN202, ANN401, E501, S101, E402, F401, F811
"""Checksum-bound upload promotion against a real PostgreSQL with row-level security on (ADR 0013, `secure_files`).

The invariant: bytes promoted from an incoming object to a final object cryptographically match
the content claim authorized for that specific upload. The claim is the SHA-256 bound to the
file's row when the ticket was issued; finalization computes the digest of the bytes itself and
promotes only on an exact match. These tests drive the real finalizer and its job against forced
row-level security, with a bucket that models the one provider behaviour that matters
(`client_copy`: an unsigned `x-amz-copy-source` turns a signed PUT into a copy). The real
provider's answers are `test_upload_finalization_provider.py`.

Skipped without a database; run as the restricted application role.
"""

from __future__ import annotations

import hashlib

import pytest
from koras_api.core.upload_window import is_incoming_key
from koras_worker.uploads.finalize import FinalizeKind
from test_upload_finalization_real import (
    A,
    B,
    _final_keys,
    _finalize,
    _row,
    _run,
    _seed,
    engine,
    pytestmark,
    session,
)
from upload_store_support import ClientCannotWrite, MemBucket

VICTIM = b"VICTIM,SECRET\ntenant-b,4242\n"
assert len(VICTIM) != len(A)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def releasable(*, status: str, scan_status: str, storage_key: str) -> bool:
    """The most this layer can say: a file is never releasable while it is unverified or on a
    key a ticket could write. The release rule proper is a later layer's; this is its floor."""
    return status == "ready" and scan_status == "clean" and not is_incoming_key(storage_key)


async def _assert_withheld(engine, tenant, file_id, incoming, bucket) -> None:
    """The row is still on the incoming key, pending and not releasable; nothing was promoted."""
    row = await _row(engine, tenant, file_id)
    assert row["storage_key"] == incoming
    assert row["scan_status"] == "pending" and row["checksum_verified_at"] is None
    assert not releasable(**{k: row[k] for k in ("status", "scan_status", "storage_key")})
    assert [k for k in _final_keys(bucket) if f"/{tenant}/" in k] == []
    assert not [c for c in bucket.calls if c[0] == "copy"], "nothing was copied to a final key"
    assert not [c for c in bucket.calls if c[0] == "delete"], "nothing was removed"


async def test_bytes_that_hash_to_the_bound_claim_are_promoted_and_corroborated(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.FINALIZED
    row = await _row(engine, tenant, file_id)
    assert row["checksum_sha256"] == sha(A) and row["checksum_verified_at"] is not None
    assert hashlib.sha256(bucket.objects[row["storage_key"]]).hexdigest() == sha(A)


async def test_same_length_altered_bytes_do_not_match_the_claim_and_are_not_promoted(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.client_put(incoming, B)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    await _assert_withheld(engine, tenant, file_id, incoming, bucket)


async def test_a_wrong_claim_is_a_mismatch_even_though_the_object_is_whole(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A, checksum_sha256=sha(B))
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    await _assert_withheld(engine, tenant, file_id, incoming, bucket)


@pytest.mark.parametrize("claim", [None, "", "not-a-digest", "AB" * 32, "ab" * 31])
async def test_a_missing_or_malformed_claim_is_held_without_touching_the_store(
    engine, session, claim
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A, checksum_sha256=claim)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    assert bucket.calls == [], "no claim means nothing is read, copied or hashed on its behalf"
    await _assert_withheld(engine, tenant, file_id, incoming, bucket)
    # The row was not given a claim: nothing here invents one.
    assert (await _row(engine, tenant, file_id))["checksum_sha256"] == claim


async def test_a_provider_copy_of_another_tenants_bytes_fails_the_attackers_own_claim(
    engine, session
) -> None:
    """The provider copy with the attacker's own checksum: the copied bytes cannot match it."""
    bucket = MemBucket()
    victim = "tenants/victim/documents/v/final/g/secret.csv"
    bucket.objects[victim] = VICTIM
    tenant, file_id, incoming = await _seed(session, bucket, A)  # claim = sha(A)
    bucket.client_copy(incoming, victim)
    # Declared at the victim's size (the real provider does not hold the signed length).
    await _set_size(engine, tenant, file_id, len(VICTIM))
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    await _assert_withheld(engine, tenant, file_id, incoming, bucket)
    assert bucket.objects[victim] == VICTIM


async def test_a_provider_copy_with_the_victims_checksum_still_has_no_provenance(
    engine, session
) -> None:
    """The inverse: the attacker knows the victim's key AND digest and claims it.

    The digest matches the copied bytes, so the hash alone would promote them. What refuses is
    provenance: a plain PUT of this ticket stores its upload id, a provider copy carries the
    source's metadata. (Whether the provider executes the copy at all is the signed
    copy-source precondition, exercised against the real store.)
    """
    bucket = MemBucket()
    victim = "tenants/victim/documents/v/final/g/secret.csv"
    bucket.objects[victim] = VICTIM
    tenant, file_id, incoming = await _seed(session, bucket, VICTIM, checksum_sha256=sha(VICTIM))
    bucket.client_copy(incoming, victim)
    assert bucket.sha256(incoming) == sha(VICTIM), "the claim and the copied bytes agree"
    bucket.calls.clear()
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    await _assert_withheld(engine, tenant, file_id, incoming, bucket)
    # Never a clean verdict, so never a release.
    row = await _row(engine, tenant, file_id)
    assert not releasable(**{k: row[k] for k in ("status", "scan_status", "storage_key")})


async def test_the_ticket_holder_cannot_write_a_final_key_to_plant_bytes_there(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    outcome = await _finalize(engine, tenant, file_id, bucket)
    with pytest.raises(ClientCannotWrite):
        bucket.client_put(outcome.key, B)
    with pytest.raises(ClientCannotWrite):
        bucket.client_copy(outcome.key, incoming)


async def test_a_final_copy_that_does_not_hash_to_the_claim_is_deleted_and_never_swapped(
    engine, session
) -> None:
    """The incoming object was fine when hashed; the copy is not (a provider fault)."""
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)

    def corrupt() -> None:
        for key in [k for k in bucket.objects if "/final/" in k]:
            bucket.objects[key] = B

    bucket.after_copy = corrupt
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.HELD
    row = await _row(engine, tenant, file_id)
    assert row["storage_key"] == incoming and row["scan_status"] == "pending"
    assert _final_keys(bucket) == [], "the unverified copy was removed"


async def test_a_write_landing_after_the_incoming_hash_cannot_change_what_is_promoted(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.after_copy = lambda: bucket.client_put(incoming, B)
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.FINALIZED
    assert hashlib.sha256(bucket.objects[outcome.key]).hexdigest() == sha(A)


async def _set_size(engine, tenant, file_id, size) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from test_upload_finalization_real import AS_TENANT

    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        await opened.execute(AS_TENANT, {"tenant_id": tenant})
        await opened.execute(
            text("update public.files set size_bytes = :s where id = cast(:f as uuid)"),
            {"s": size, "f": file_id},
        )
        await opened.commit()
