# ruff: noqa: ANN001, ANN201, ANN003, ANN202, ANN401, E501, S101, E402, S310, F401, F811
"""Provider qualification: the cases the upload suites do not state outright (ADR 0013 sections 6, 9).

`tooling/promotion/provider_qualification.py` runs the upload attack matrix against a target
environment's own object store. Most rows already exist in `test_upload_checksum_provider.py` and
`test_upload_finalization_provider.py`; this file adds what those do not say:

    Q04  an unsigned `x-amz-copy-source` header on a ticket, stated on its own (matrix 4)
    Q12  the attacker holds a PREVIOUSLY ISSUED presigned DOWNLOAD URL for the victim object
         (its key, its signature, its bytes) and tries every use of it
    Q13  FORGED, NON-EMPTY provenance on an intentionally UNGUARDED copy-source ticket (matrix 12)

The invariant of Q04 and Q12: possession of another tenant's storage key, checksum, metadata or a
previously issued download URL must not let THOSE bytes become releasable through the attacker's
file. (Bytes the attacker fetched with a legitimately issued URL and then uploaded themselves are
the attacker's own upload; Q12d proves that this is an ordinary upload, never a link to the
victim's object, and records it as the residual no storage control can remove.)

**Q13 is the ADR 0013 section 9 regression.** The finalizer must require that the incoming
object's provenance EQUALS the expected upload identity (the upload id in the ticket's own key),
not merely that it is non-empty. The existing cases cover the provenance being absent
(`test_D_...` D2 and D3 copy from a victim object that carries no provenance at all) and a forged
header on a *guarded* ticket (the provider refuses it, nothing lands). Neither puts a forged
non-empty provenance on an object that LANDED. Q13 does: the ticket is built unguarded (the
harness's own `Run.ticket(guarded=False)`, test-only mechanics: no production code path signs a
ticket without the guard, and no production guard is touched), the provider copies, and what the
object carries is non-empty, is not this ticket's upload id, and whose bytes DO hash to the
claim -- so the provenance check is the only thing that can refuse. A finalizer that accepted
"any non-empty provenance" would promote every one of these; that is what the mutation check in
`docs/SECURE_FILES.md` ("Promotion tooling") shows this case catching.

Disposable objects only, under random tenant prefixes, all deleted and listed empty at the end.
No historical file is read, listed or written. Prints no credential or signature.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest
from koras_api.core.upload_window import incoming_key, is_incoming_key
from koras_storage import UPLOAD_PROVENANCE_META, upload_guard_headers
from koras_worker.uploads.finalize import FinalizeKind
from test_upload_checksum_provider import (
    VICTIM,
    _assert_not_releasable,
    copy_headers,
    metadata_only_ticket,
    releasable,
    sha,
    victim,
)
from test_upload_finalization_provider import (
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

# --- Q04: unsigned copy-source, stated on its own -----------------------------------------------


async def test_Q04_an_unsigned_copy_source_header_never_lands_another_tenants_bytes(
    engine, run, victim
) -> None:
    # Guarded ticket (what the API issues), attacker's own honest claim: refused, nothing lands.
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(VICTIM), claim=A)
    status = run.put(url, b"X" * len(VICTIM), extra=copy_headers(run, victim))
    print(f"EVIDENCE Q04_guarded_status={status}")
    assert status in {403, 412}
    assert run.keys() == []
    assert run.get(victim) == VICTIM

    # Ticket with no guard at all (a provider that ignored it): the bytes land, the claim for
    # the attacker's own content cannot match them, and nothing becomes releasable.
    file_2 = str(uuid.uuid4())
    key_2, url_2 = run.ticket(file_2, len(VICTIM), guarded=False)
    assert run.put(url_2, b"X" * len(VICTIM), extra=copy_headers(run, victim)) == 200
    await _seed(engine, run, file_2, key_2, len(VICTIM), claim=A)
    job = await _job(engine, run, file_2)
    assert job["status"] == "held"
    assert job["failure"] == "integrity_mismatch"
    await _assert_not_releasable(engine, run, file_2, key_2)


# --- Q12: a previously issued presigned DOWNLOAD URL for the victim ---------------------------


def _fetch(url: str, *, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - presigned
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _key_from(url: str, run: Run) -> str:
    """What a URL holder reads straight out of the path: the victim object's key."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    return path[path.index("/tenants/") + 1 :]


@pytest.fixture
def download(run: Run, victim: str) -> str:
    """The URL the victim's tenant was once issued; the attacker kept it."""
    url = run.store.presign_download(victim, "secret.csv", 900)
    status, body = _fetch(url)
    assert status == 200 and body == VICTIM, "the URL does what it was issued to do"
    return url


async def test_Q12a_the_download_url_as_a_copy_source_on_a_guarded_ticket_lands_nothing(
    engine, run, victim, download
) -> None:
    learned = _key_from(download, run)
    assert learned == victim
    query = urllib.parse.urlsplit(download).query
    variants = {
        "key": f"/{run.bucket}/{learned}",
        "key_with_signature": f"/{run.bucket}/{learned}?{query}",
        "bare_key": f"{run.bucket}/{learned}",
        "encoded_key": f"/{run.bucket}/{urllib.parse.quote(learned, safe='')}",
    }
    for name, source in variants.items():
        file_id = str(uuid.uuid4())
        key, url = run.ticket(file_id, len(VICTIM), claim=VICTIM)  # the victim's own checksum
        status = run.put(url, b"X" * len(VICTIM), extra={"x-amz-copy-source": source})
        print(f"EVIDENCE Q12a_{name}_status={status}")
        assert status in {400, 403, 404, 412}, name
        assert run.keys() == [], f"{name}: nothing landed on the incoming key"
        await _seed(engine, run, file_id, key, len(VICTIM), claim=VICTIM)
        job = await _job(engine, run, file_id)
        assert job["status"] == "held", name
        await _assert_not_releasable(engine, run, file_id, key)
        assert run.get(victim) == VICTIM


async def test_Q12b_the_download_url_on_an_unguarded_ticket_is_held_for_want_of_provenance(
    engine, run, victim, download
) -> None:
    """Models a provider that ignores the signed guard: even then the bytes are not promoted."""
    learned = _key_from(download, run)
    for source in (
        f"/{run.bucket}/{learned}",
        f"/{run.bucket}/{learned}?{urllib.parse.urlsplit(download).query}",
    ):
        file_id = str(uuid.uuid4())
        key, url = run.ticket(file_id, len(VICTIM), guarded=False)
        status = run.put(url, b"X" * len(VICTIM), extra={"x-amz-copy-source": source})
        print(f"EVIDENCE Q12b_unguarded_status={status}")
        await _seed(engine, run, file_id, key, len(VICTIM), claim=VICTIM)
        outcome = await _finalize(engine, run, file_id)
        # Whatever the provider did, the victim's bytes never reach a final key for this file.
        assert outcome.kind is not FinalizeKind.FINALIZED
        row = await _row(engine, run, file_id)
        assert row["storage_key"] == key and row["checksum_verified_at"] is None
        assert not releasable(
            status=row["status"], scan_status=row["scan_status"], storage_key=row["storage_key"]
        )
        assert not [k for k in run.keys() if "/final/" in k]
        assert run.get(victim) == VICTIM
        run.clean_up()


async def test_Q12c_the_download_signature_cannot_write_delete_or_be_re_aimed(
    engine, run, victim, download
) -> None:
    before = run.etag(victim)
    # The GET signature used as a PUT or DELETE on the victim's own key.
    put_status = run.put(download, B, only={"Content-Type": "text/csv"})
    delete_status, _ = _fetch(download, method="DELETE")
    print(f"EVIDENCE Q12c_put_status={put_status} delete_status={delete_status}")
    assert put_status in {400, 401, 403}
    assert delete_status in {400, 401, 403, 405}
    assert run.get(victim) == VICTIM and run.etag(victim) == before

    # The GET signature re-aimed at a key the attacker chooses, as a PUT.
    attacker_key = f"tenants/{run.tenant}/documents/{uuid.uuid4()}/incoming/{uuid.uuid4()}/a.csv"
    reaimed = run.put(download, VICTIM, path_key=attacker_key, only={"Content-Type": "text/csv"})
    print(f"EVIDENCE Q12c_reaimed_status={reaimed}")
    assert reaimed in {400, 401, 403}
    assert run.keys() == []

    # The download URL's query string glued onto the path of an upload ticket's key.
    file_id = str(uuid.uuid4())
    key, ticket_url = run.ticket(file_id, len(VICTIM), claim=VICTIM)
    split = urllib.parse.urlsplit(ticket_url)
    spliced = f"{split.scheme}://{split.netloc}{split.path}?{urllib.parse.urlsplit(download).query}"
    spliced_status = run.put(spliced, VICTIM, only={"Content-Type": "text/csv"})
    print(f"EVIDENCE Q12c_spliced_status={spliced_status}")
    assert spliced_status in {400, 401, 403}
    assert run.keys() == []
    assert run.get(victim) == VICTIM


async def test_Q12d_a_download_url_gives_no_object_the_attacker_may_release_other_than_by_uploading(
    engine, run, victim, download
) -> None:
    """The residual, stated exactly: bytes obtained through the URL are bytes the holder has.

    Uploading them with the victim's checksum through the attacker's own ticket is an ordinary
    upload (the object carries this ticket's own upload id, it is a copy at the attacker's tenant
    prefix, and it is a different object from the victim's). What must NOT happen is any link
    between the two: the victim's object is untouched, is never named by the attacker's row and
    is never what the attacker's file releases.
    """
    status, fetched = _fetch(download)
    assert status == 200 and sha(fetched) == sha(VICTIM)
    before = run.etag(victim)
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(fetched), claim=fetched)
    assert run.put(url, fetched) == 200
    meta = run.client.head_object(Bucket=run.bucket, Key=key)["Metadata"]
    assert meta == {UPLOAD_PROVENANCE_META: key.split("/")[5]}, (
        "the attacker's own PUT, nothing else"
    )
    await _seed(engine, run, file_id, key, len(fetched), claim=fetched)
    job = await _job(engine, run, file_id)
    assert job["status"] == "finalized"
    row = await _row(engine, run, file_id)
    assert row["storage_key"] != victim and row["storage_key"].startswith(f"tenants/{run.tenant}/")
    assert not is_incoming_key(row["storage_key"])
    assert run.get(victim) == VICTIM and run.etag(victim) == before, (
        "the victim object is untouched"
    )
    # Deleting the attacker's file's object never reaches the victim's object either.
    run.store.delete(row["storage_key"])
    assert run.get(victim) == VICTIM


# --- Q13: forged, NON-EMPTY provenance on an intentionally UNGUARDED copy-source ticket ---------


@pytest.fixture
def provenanced_victim(run: Run):
    """Another tenant's object that carries a non-empty provenance of its OWN (its own upload id).

    This is what a real victim object looks like after a guarded upload: the copy a provider
    makes from it brings that metadata along, so the attacker's object ends up holding a
    plausible, non-empty, valid-looking upload id that is not the attacker's ticket's.
    """
    other = str(uuid.uuid4())
    own_upload = str(uuid.uuid4())
    key = f"tenants/{other}/documents/{uuid.uuid4()}/final/{uuid.uuid4()}/secret.csv"
    run.client.put_object(
        Bucket=run.bucket,
        Key=key,
        Body=VICTIM,
        ContentType="text/csv",
        Metadata={UPLOAD_PROVENANCE_META: own_upload},
    )
    try:
        yield key, own_upload
    finally:
        run.store.delete(key)
        left = run.client.list_objects_v2(Bucket=run.bucket, Prefix=f"tenants/{other}/")
        assert left.get("KeyCount", 0) == 0, "the victim object was not cleaned up"


def _provenance(run: Run, key: str) -> str | None:
    return run.client.head_object(Bucket=run.bucket, Key=key)["Metadata"].get(
        UPLOAD_PROVENANCE_META
    )


def forged_signed_ticket(
    run: Run, file_id: str, size: int, claim: bytes, forged: str
) -> tuple[str, str]:
    """A ticket that signs a FORGED provenance (test-only mechanics, never a production path).

    Built with the real `presign_upload`, passing it an upload id that is not the one in the key.
    The URL carries the copy-source preconditions as the API's does, so only the provenance is
    wrong: a plain PUT of the attacker's own bytes lands with a non-empty provenance that is not
    this ticket's upload identity.
    """
    import base64

    upload_id = str(uuid.uuid4())
    key = incoming_key(run.tenant, "documents", file_id, upload_id, "a.csv")
    url = run.store.presign_upload(key, "text/csv", size, 600, sha(claim), provenance=forged)
    run.headers[url] = {
        "Content-Type": "text/csv",
        "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha(claim))).decode(),
        **upload_guard_headers(forged),
    }
    return key, url


def _unguarded(run: Run, file_id: str, size: int, claim: bytes, forged: str) -> tuple[str, str]:
    return run.ticket(file_id, size, guarded=False)


def _metadata_only(run: Run, file_id: str, size: int, claim: bytes, forged: str) -> tuple[str, str]:
    return metadata_only_ticket(run, file_id, size, claim)


TICKETS = {
    "unguarded": _unguarded,  # a provider that ignored the guard
    "metadata_only": _metadata_only,  # signs the provenance and not the copy preconditions
    "forged_signed": forged_signed_ticket,  # signs a forged provenance
}


async def _attempt(
    engine,
    run: Run,
    name: str,
    *,
    ticket: str,
    claim: bytes,
    body: bytes,
    extra: dict[str, str] | None = None,
    forged: str = "forged",
    must_land: bool = True,
):
    """One PUT on a deliberately weakened ticket, then the REAL finalizer.

    Returns `(landed, key, provenance carried, sha of what landed, outcome, file id)`. `must_land`: the
    scenario's premise is that the provider executed the request; a provider that refuses a
    request it was never signed to refuse (an unsigned metadata header, say) leaves nothing on the
    incoming key, which is also a pass and is asserted as such. The tickets exist only here:
    `Run.ticket(guarded=False)` and the two builders above are this harness's own mechanics, and
    the API never issues any of them.
    """
    file_id = str(uuid.uuid4())
    key, url = TICKETS[ticket](run, file_id, len(body), claim, forged)
    expected_upload = key.split("/")[5]
    status = run.put(url, body, extra=extra)
    print(f"EVIDENCE Q13_{name}_put_status={status}")
    if status != 200:
        assert not must_land, f"{name}: the premise failed: the provider did not execute the PUT"
        assert run.keys() == [], f"{name}: a refused request left an object behind"
        return False, key, None, None, None, file_id
    carried = _provenance(run, key)
    assert carried != expected_upload, f"{name}: the object must not carry this ticket's identity"
    landed_sha = sha(run.get(key) or b"")  # what landed, read BEFORE the finalizer touches it
    await _seed(engine, run, file_id, key, len(body), claim=claim)
    outcome = await _finalize(engine, run, file_id)
    return True, key, carried, landed_sha, outcome, file_id


async def _assert_refused(engine, run: Run, name: str, key: str, outcome, file_id: str) -> None:
    print(f"EVIDENCE Q13_{name}_outcome={outcome.kind.value} failure={outcome.failure}")
    assert outcome.kind is FinalizeKind.HELD, f"{name}: a forged provenance must be refused"
    assert outcome.failure is not None and outcome.failure.value == "integrity_mismatch", name
    await _assert_not_releasable(engine, run, file_id, key)


async def test_Q13_a_forged_nonempty_provenance_on_an_unguarded_copy_source_ticket_is_refused(
    engine, run, provenanced_victim
) -> None:
    victim_key, victim_upload = provenanced_victim
    copy = copy_headers(run, victim_key)
    # The victim's bytes and the victim's digest: the digest checks would PASS, so the provenance
    # equality is the only thing that can refuse.
    scenarios = {
        # The provider copies the victim's object WITH its metadata (directive COPY, the default):
        # a valid-looking, non-empty upload id that belongs to somebody else's ticket.
        "copied_victim_provenance": dict(ticket="unguarded", extra=copy, must_land=True),
        # The same through the ticket that signs the provenance but not the copy preconditions.
        "metadata_only_ticket_copy": dict(ticket="metadata_only", extra=copy, must_land=True),
        # The client asks the provider to REPLACE the metadata with its own forged value. A provider
        # that insists every x-amz header be signed refuses this one, and nothing lands.
        "replaced_with_forged_string": dict(
            ticket="unguarded",
            extra={
                **copy,
                "x-amz-metadata-directive": "REPLACE",
                f"x-amz-meta-{UPLOAD_PROVENANCE_META}": "forged-" + uuid.uuid4().hex,
            },
            must_land=False,
        ),
        # Replaced with a well-formed upload id that is not this ticket's (a sibling ticket's).
        "replaced_with_a_sibling_upload_id": dict(
            ticket="unguarded",
            extra={
                **copy,
                "x-amz-metadata-directive": "REPLACE",
                f"x-amz-meta-{UPLOAD_PROVENANCE_META}": str(uuid.uuid4()),
            },
            must_land=False,
        ),
    }
    landed_forged = 0
    for name, scenario in scenarios.items():
        landed, key, carried, landed_sha, outcome, file_id = await _attempt(
            engine, run, name, claim=VICTIM, body=b"X" * len(VICTIM), **scenario
        )
        if landed:
            if carried:
                landed_forged += 1
            # Refusal first: a finalizer that promoted these bytes fails HERE, naming the case.
            await _assert_refused(engine, run, name, key, outcome, file_id)
            assert landed_sha == sha(VICTIM), f"{name}: the digest is not what refuses"
        assert run.get(victim_key) == VICTIM, f"{name}: the victim object is untouched"
        run.clean_up()
    assert landed_forged >= 1, (
        "no scenario landed a forged non-empty provenance: the case is vacuous"
    )

    # The attacker's OWN bytes with an honest digest and a forged provenance that is signed into
    # the ticket (no copy at all): refused, because identity is not the digest.
    landed, key, carried, landed_sha, outcome, file_id = await _attempt(
        engine, run, "own_bytes_signed_forged", ticket="forged_signed", claim=A, body=A,
        forged="forged-" + uuid.uuid4().hex,
    )  # fmt: skip
    assert landed and carried
    await _assert_refused(engine, run, "own_bytes_signed_forged", key, outcome, file_id)
    assert landed_sha == sha(A), "the digest is honest here: only the provenance is forged"
    run.clean_up()

    # The digest requirement still applies, independently: forged provenance AND a claim that the
    # landed bytes do not match.
    landed, key, carried, landed_sha, outcome, file_id = await _attempt(
        engine, run, "forged_and_wrong_digest", ticket="unguarded", claim=A,
        body=b"X" * len(VICTIM), extra=copy,
    )  # fmt: skip
    assert landed
    await _assert_refused(engine, run, "forged_and_wrong_digest", key, outcome, file_id)
    assert landed_sha != sha(A), "the landed bytes are not the claimed ones"
    run.clean_up()

    # The positive control: the same finalizer promotes an honest, guarded upload, so the
    # refusals above are the provenance and digest checks and not a finalizer that refuses all.
    honest_file = str(uuid.uuid4())
    honest_key, honest_url = run.ticket(honest_file, len(A), claim=A)
    assert run.put(honest_url, A) == 200
    assert _provenance(run, honest_key) == honest_key.split("/")[5]
    await _seed(engine, run, honest_file, honest_key, len(A), claim=A)
    promoted = await _finalize(engine, run, honest_file)
    assert promoted.kind is FinalizeKind.FINALIZED
    run.clean_up()
