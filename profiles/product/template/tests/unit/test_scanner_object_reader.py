# ruff: noqa: ANN401, S106
# Test doubles that stand in for a boto3 client take its arbitrary keyword arguments,
# and the settings carry placeholder keys for a client that never connects.
"""The bounded object reader, the identity checks and the upload-window gate.

Frozen time, a scripted object source, no network, no sleeping. What is asserted
is the object gate and only the object gate: it can say READY or one of a set of
holds, and none of it is a verdict. Nothing here, or in the module under test,
can mark a file clean, infected or skipped.
"""

from __future__ import annotations

import ast
import base64
import dataclasses
import inspect
import io
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from botocore.exceptions import ClientError, EndpointConnectionError  # noqa: E402
from botocore.response import StreamingBody  # noqa: E402
from botocore.stub import Stubber  # noqa: E402
from koras_api.core import upload_window  # noqa: E402
from koras_storage import S3ObjectStore, StorageSettings, resolve_destination  # noqa: E402
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    MAX_SCAN_BYTES,
    Admission,
    Disposition,
    ObjectGate,
    ObjectIdentity,
    ObjectReader,
    ObjectReference,
    ObjectReferenceError,
    ObjectSourceError,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    UploadWindowUnavailable,
    earliest_read,
)
from koras_worker.scanning import objects as objects_module  # noqa: E402
from koras_worker.scanning.s3 import S3ObjectSource, default_bucket_source  # noqa: E402
from object_support import (  # noqa: E402
    FILE,
    ISSUED,
    KEY,
    OTHER_FILE,
    OTHER_TENANT,
    STAMP,
    TENANT,
    FakeObjectSource,
    FirstChunkScanner,
    identity,
)
from scanner_support import FakeScanner  # noqa: E402

SCANNING_DIR = Path(scanning.__file__).parent
REPO = SCANNING_DIR.parents[3]
BODY = b"0123456789" * 10  # 100 bytes


def ref(key: str = KEY, tenant: str = TENANT, file: str = FILE) -> ObjectReference:
    return ObjectReference(tenant, file, key)


def reader(
    source: FakeObjectSource,
    *,
    now: datetime = ISSUED + timedelta(minutes=16),
    max_bytes: int = 1000,
    chunk_bytes: int = 16,
) -> ObjectReader:
    return ObjectReader(source, max_bytes=max_bytes, chunk_bytes=chunk_bytes, clock=lambda: now)


def source_for(body: bytes = BODY, **overrides: object) -> FakeObjectSource:
    ident = identity(len(body), **overrides)
    return FakeObjectSource(stats=[ident], body=body)


async def run(
    source: FakeObjectSource, scanner: Any = None, **reader_args: Any
) -> tuple[Admission, ScanResult | None, Any]:
    """Admit, stream into a scanner, verify: the sequence a worker will run."""
    r = reader(source, **reader_args)
    admission = await r.admit(ref(), ISSUED)
    if not admission.ready:
        return admission, None, None
    stream = r.stream(ref(), admission)
    result = await (scanner or FakeScanner.candidate_clean()).scan(stream)
    return admission, result, await r.verify(ref(), admission, stream)


# --- the upload window: items 1-3 -------------------------------------------------


def test_the_canonical_minimum_delay_is_sixteen_minutes() -> None:
    assert upload_window.UPLOAD_URL_SECONDS == 15 * 60
    assert upload_window.UPLOAD_SAFETY_MARGIN_SECONDS == 60
    assert upload_window.SCAN_READ_DELAY_SECONDS == 16 * 60
    assert earliest_read(ISSUED) == ISSUED + timedelta(minutes=16)


@pytest.mark.parametrize(
    "elapsed",
    [
        timedelta(0),
        timedelta(minutes=1),
        timedelta(minutes=15),
        timedelta(minutes=15, seconds=59),
        timedelta(minutes=15, seconds=59, microseconds=999_999),
        timedelta(seconds=-5),  # a clock behind the database
    ],
)
async def test_before_the_boundary_nothing_is_read(elapsed: timedelta) -> None:
    source = source_for()
    admission = await reader(source, now=ISSUED + elapsed).admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.WINDOW_NOT_ELAPSED
    assert not admission.ready
    assert admission.identity is None
    assert admission.opens_at == ISSUED + timedelta(minutes=16)
    assert admission.retry_after == timedelta(minutes=16) - elapsed
    # Not even metadata: the store was never asked.
    assert source.calls == []


async def test_exactly_at_the_boundary_is_allowed() -> None:
    source = source_for()
    admission = await reader(source, now=ISSUED + timedelta(minutes=16)).admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.READY


@pytest.mark.parametrize(
    "elapsed",
    [timedelta(minutes=16, microseconds=1), timedelta(minutes=16, seconds=1), timedelta(hours=3)],
)
async def test_after_the_boundary_is_allowed(elapsed: timedelta) -> None:
    admission = await reader(source_for(), now=ISSUED + elapsed).admit(ref(), ISSUED)
    assert admission.ready


async def test_a_deferral_is_not_a_failure_and_not_an_attempt() -> None:
    admission = await reader(source_for(), now=ISSUED).admit(ref(), ISSUED)
    assert admission.gate.failure is None
    assert not admission.gate.counts_attempt


async def test_the_gate_uses_the_tickets_own_time_and_not_the_clocks_date() -> None:
    later = ISSUED + timedelta(days=2)
    source = source_for()
    admission = await reader(source, now=later + timedelta(minutes=15)).admit(ref(), later)
    assert admission.gate is ObjectGate.WINDOW_NOT_ELAPSED
    assert source.calls == []


async def test_a_non_utc_issue_time_is_compared_as_an_instant() -> None:
    local = ISSUED.astimezone(timezone(timedelta(hours=2)))
    assert local == ISSUED and local.utcoffset() != ISSUED.utcoffset()
    blocked = await reader(source_for(), now=ISSUED + timedelta(minutes=15, seconds=59)).admit(
        ref(), local
    )
    allowed = await reader(source_for(), now=ISSUED + timedelta(minutes=16)).admit(ref(), local)
    assert blocked.gate is ObjectGate.WINDOW_NOT_ELAPSED
    assert allowed.ready


def test_naive_times_are_refused_rather_than_compared_against_the_wrong_clock() -> None:
    with pytest.raises(ValueError):
        upload_window.earliest_scan_read(datetime(2026, 10, 4, 12, 0, 0))
    with pytest.raises(ValueError):
        earliest_read(datetime(2026, 10, 4, 12, 0, 0))


async def test_a_naive_clock_is_refused() -> None:
    r = ObjectReader(source_for(), clock=lambda: datetime(2026, 10, 4, 12, 30))
    with pytest.raises(ValueError):
        await r.admit(ref(), ISSUED)


async def test_an_unevaluable_window_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(objects_module.importlib, "import_module", refuse)
    source = source_for()
    with pytest.raises(UploadWindowUnavailable):
        await reader(source).admit(ref(), ISSUED)
    assert source.calls == []


def test_the_route_and_the_gate_read_one_constant() -> None:
    files = (REPO / "services/api/koras_api/routers/files.py").read_text(encoding="utf-8")
    tree = ast.parse(files)
    assigned = [
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    ]
    assert "UPLOAD_URL_SECONDS" not in assigned, "the route must import the shared constant"
    assert "from ..core.upload_window import UPLOAD_URL_SECONDS" in files
    # The ticket's lifetime and the signature's both come from it.
    assert files.count("UPLOAD_URL_SECONDS") >= 3


def test_presign_upload_has_exactly_one_call_site() -> None:
    sites = []
    for path in (REPO / "services").rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "presign_upload"
            ):
                sites.append(path.name)
    assert sites == ["files.py"], sites


def test_the_worker_image_carries_the_shared_window_file() -> None:
    dockerfile = (REPO / "services/worker/Dockerfile").read_text(encoding="utf-8")
    assert "services/api/koras_api/core/upload_window.py" in dockerfile


# --- admission outcomes: items 4-7 -----------------------------------------------


async def test_a_missing_object() -> None:
    source = FakeObjectSource(stats=[None])
    admission = await reader(source).admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.MISSING
    assert admission.gate.failure is ScanFailure.OBJECT_UNREACHABLE
    assert admission.gate.counts_attempt
    assert source.verbs == ["stat"]


@pytest.mark.parametrize(
    "error",
    [
        ObjectSourceError("refused"),
        ConnectionResetError("reset"),
        TimeoutError("slow"),
        RuntimeError("anything at all"),
    ],
)
async def test_an_unreachable_store(error: Exception) -> None:
    source = FakeObjectSource(stats=[error])
    admission = await reader(source).admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.UNREACHABLE
    assert admission.gate.failure is ScanFailure.OBJECT_UNREACHABLE
    assert not admission.ready


async def test_an_object_exactly_at_the_ceiling_is_admitted_and_read_in_full() -> None:
    body = b"x" * 1000
    admission, result, check = await run(source_for(body), max_bytes=1000)
    assert admission.ready
    assert result is not None and result.candidate_clean
    assert check.passed
    assert check.bytes_read == 1000


async def test_an_object_one_byte_over_the_ceiling_is_refused_unread() -> None:
    source = source_for(b"x" * 1001)
    admission = await reader(source, max_bytes=1000).admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.OVERSIZED
    assert admission.gate.failure is ScanFailure.OVER_CEILING
    assert not admission.gate.counts_attempt
    assert source.verbs == ["stat"]


async def test_the_ratified_hundred_mib_ceiling() -> None:
    assert MAX_SCAN_BYTES == 100 * 1024 * 1024
    over = FakeObjectSource(stats=[identity(MAX_SCAN_BYTES + 1)])
    r = ObjectReader(over, clock=lambda: ISSUED + timedelta(minutes=16))
    assert (await r.admit(ref(), ISSUED)).gate is ObjectGate.OVERSIZED
    assert over.verbs == ["stat"]

    exact = FakeObjectSource(stats=[identity(MAX_SCAN_BYTES)])
    r = ObjectReader(exact, chunk_bytes=1024 * 1024, clock=lambda: ISSUED + timedelta(minutes=16))
    admission = await r.admit(ref(), ISSUED)
    assert admission.ready
    stream = r.stream(ref(), admission)
    result = await FakeScanner.candidate_clean().scan(stream)
    assert result.candidate_clean
    assert stream.bytes_read == MAX_SCAN_BYTES
    assert (await r.verify(ref(), admission, stream)).passed


def test_the_ceiling_cannot_be_raised_past_the_ratified_limit() -> None:
    with pytest.raises(ValueError):
        ObjectReader(FakeObjectSource(stats=[None]), max_bytes=MAX_SCAN_BYTES + 1)
    with pytest.raises(ValueError):
        ObjectReader(FakeObjectSource(stats=[None]), max_bytes=0)
    with pytest.raises(ValueError):
        ObjectReader(FakeObjectSource(stats=[None]), chunk_bytes=2 * 1024 * 1024)


async def test_a_store_that_understates_the_size_cannot_outrun_the_ceiling() -> None:
    # Metadata says 10 bytes under a 50 byte ceiling; the read has far more.
    source = FakeObjectSource(stats=[identity(10)], served=10_000)
    r = reader(source, max_bytes=50, chunk_bytes=16)
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    result = await FakeScanner.candidate_clean().scan(stream)
    assert result.outcome is ScanOutcome.READ_FAILURE
    check = await r.verify(ref(), admission, stream)
    assert check.gate in {ObjectGate.OVERSIZED, ObjectGate.CHANGED}
    assert not check.passed
    # Memory is bounded by the ceiling, not by what the store offers: at most
    # ceiling + 1 bytes were ever requested.
    assert sum(source.opened[0].requested) <= 50 + 1


async def test_a_stream_never_requests_more_than_one_chunk_or_one_byte_past_the_ceiling() -> None:
    source = source_for(b"y" * 100)
    r = reader(source, max_bytes=100, chunk_bytes=30)
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    await FakeScanner.candidate_clean().scan(stream)
    requested = source.opened[0].requested
    assert max(requested) <= 30
    assert sum(requested) <= 101 + 30


async def test_chunks_are_small() -> None:
    sizes: list[int] = []

    class Spy:
        async def scan(self, source: Any) -> ScanResult:
            async for block in source:
                sizes.append(len(block))
            return ScanResult(ScanOutcome.CANDIDATE_CLEAN)

        async def ping(self) -> bool:
            return True

    await run(source_for(), scanner=Spy(), chunk_bytes=16)
    assert sizes and max(sizes) <= 16 and sum(sizes) == len(BODY)


async def test_an_expected_size_that_differs_is_not_the_uploaded_object() -> None:
    source = source_for()
    admission = await reader(source).admit(ref(), ISSUED, expected_size=len(BODY) + 1)
    assert admission.gate is ObjectGate.CHANGED
    assert source.verbs == ["stat"]
    ok = await reader(source_for()).admit(ref(), ISSUED, expected_size=len(BODY))
    assert ok.ready


async def test_a_store_that_cannot_tell_objects_apart_is_insufficient() -> None:
    for weak in (
        identity(len(BODY), etag=None),
        identity(len(BODY), etag=None, last_modified=None),
        identity(len(BODY), etag="", version_id=""),
    ):
        source = FakeObjectSource(stats=[weak], body=BODY)
        admission = await reader(source).admit(ref(), ISSUED)
        assert admission.gate is ObjectGate.IDENTITY_INSUFFICIENT, weak
        assert admission.gate.failure is ScanFailure.IDENTITY_INSUFFICIENT
        assert source.verbs == ["stat"], "an object that cannot be bound is never opened"


@pytest.mark.parametrize(
    "overrides",
    [
        {"etag": "e"},
        {"etag": None, "version_id": "v1"},
        {"etag": None, "provider_sha256": "ab" * 32},
    ],
)
async def test_any_one_strong_marker_is_sufficient(overrides: dict[str, object]) -> None:
    assert (await reader(source_for(**overrides)).admit(ref(), ISSUED)).ready


# --- changed during the operation: items 8-11 -----------------------------------


async def test_an_unchanged_object_passes() -> None:
    source = source_for(version_id="v1", provider_sha256="cd" * 32)
    admission, result, check = await run(source)
    assert admission.ready and result is not None and result.candidate_clean
    assert check.passed and check.gate is ObjectGate.READY
    assert check.bytes_read == len(BODY)
    assert source.verbs == ["stat", "open", "stat"]
    assert source.opened[0].closed


@pytest.mark.parametrize(
    ("after", "label"),
    [
        (identity(len(BODY) + 1), "size grew"),
        (identity(len(BODY) - 1), "size shrank"),
        (identity(len(BODY), etag="etag-2"), "etag changed, same length"),
        (identity(len(BODY), etag=None), "etag vanished"),
        (identity(len(BODY), last_modified=STAMP + timedelta(seconds=1)), "last-modified moved"),
        (identity(len(BODY), last_modified=None), "last-modified vanished"),
        (identity(len(BODY), version_id="v2"), "version appeared"),
        (identity(len(BODY), provider_sha256="ee" * 32), "digest appeared"),
    ],
)
async def test_an_object_that_changed_during_the_operation_fails_closed(
    after: ObjectIdentity, label: str
) -> None:
    before = identity(len(BODY))
    source = FakeObjectSource(stats=[before, after], body=BODY)
    admission, result, check = await run(source)
    assert admission.ready
    assert result is not None and result.candidate_clean, "the engine still said OK"
    assert check.gate is ObjectGate.CHANGED, label
    assert not check.passed
    assert check.gate.failure is ScanFailure.OBJECT_CHANGED


async def test_a_changed_digest_is_a_change_even_when_the_etag_is_the_same() -> None:
    source = FakeObjectSource(
        stats=[
            identity(len(BODY), provider_sha256="aa" * 32),
            identity(len(BODY), provider_sha256="bb" * 32),
        ],
        body=BODY,
    )
    assert (await run(source))[2].gate is ObjectGate.CHANGED


async def test_the_same_etag_alone_does_not_prove_the_same_bytes_when_a_digest_differs() -> None:
    a = identity(5, provider_sha256="aa" * 32)
    b = identity(5, provider_sha256="bb" * 32)
    assert a.etag == b.etag and not a.same_object(b)


async def test_last_modified_is_compared_to_the_second_not_the_microsecond() -> None:
    before = identity(len(BODY), last_modified=STAMP)
    after = identity(len(BODY), last_modified=STAMP + timedelta(microseconds=400))
    assert before == after
    source = FakeObjectSource(stats=[before, after], body=BODY)
    assert (await run(source))[2].passed


async def test_last_modified_is_normalised_across_offsets() -> None:
    plus_two = STAMP.astimezone(timezone(timedelta(hours=2)))
    assert identity(1, last_modified=plus_two) == identity(1, last_modified=STAMP)
    assert identity(1, last_modified=STAMP.replace(tzinfo=None)) == identity(1, last_modified=STAMP)


# --- HEAD-vs-GET last-modified tolerance ------------------------------------------
#
# A real S3-compatible store was seen rendering one object's LastModified one second
# apart on HeadObject and GetObject. Only that comparison tolerates it, by at most one
# second; every other piece of evidence, and the check after the read, stays exact.


def _open_differs(open_identity: ObjectIdentity) -> FakeObjectSource:
    return FakeObjectSource(
        stats=[identity(len(BODY), version_id="v1", provider_sha256="cd" * 32)],
        open_identity=open_identity,
        body=BODY,
    )


@pytest.mark.parametrize("drift", [0, 1, -1])
async def test_a_read_whose_last_modified_is_within_one_second_of_the_head_is_accepted(
    drift: int,
) -> None:
    source = _open_differs(
        identity(
            len(BODY),
            last_modified=STAMP + timedelta(seconds=drift),
            version_id="v1",
            provider_sha256="cd" * 32,
        )
    )
    _, result, check = await run(source)
    assert result is not None and result.candidate_clean
    assert check.passed, drift


@pytest.mark.parametrize("drift", [2, -2, 60])
async def test_a_read_whose_last_modified_is_more_than_one_second_off_is_object_changed(
    drift: int,
) -> None:
    source = _open_differs(
        identity(
            len(BODY),
            last_modified=STAMP + timedelta(seconds=drift),
            version_id="v1",
            provider_sha256="cd" * 32,
        )
    )
    _, result, check = await run(source)
    assert result is not None and result.outcome is ScanOutcome.READ_FAILURE
    assert check.gate is ObjectGate.CHANGED and check.gate.failure is ScanFailure.OBJECT_CHANGED
    assert sum(source.opened[0].requested) == 0, "nothing was read from the drifted object"


@pytest.mark.parametrize(
    "changed",
    [
        {"etag": "etag-2"},
        {"etag": None},
        {"size": len(BODY) + 1},
        {"size": len(BODY) - 1},
        {"version_id": "v2"},
        {"version_id": None},
        {"provider_sha256": "ee" * 32},
    ],
    ids=str,
)
@pytest.mark.parametrize("drift", [0, 1, -1])
async def test_a_tolerated_timestamp_never_excuses_other_changed_evidence(
    changed: dict[str, object], drift: int
) -> None:
    fields: dict[str, object] = {
        "last_modified": STAMP + timedelta(seconds=drift),
        "version_id": "v1",
        "provider_sha256": "cd" * 32,
    }
    fields.update(changed)
    size = int(fields.pop("size", len(BODY)))  # type: ignore[call-overload]
    source = _open_differs(identity(size, **fields))
    _, _, check = await run(source)
    assert check.gate is ObjectGate.CHANGED and not check.passed


async def test_a_timestamp_present_on_one_side_only_is_still_a_difference() -> None:
    a = identity(5)
    b = identity(5, last_modified=None)
    tolerance = timedelta(seconds=1)
    assert not a.same_object(b, last_modified_tolerance=tolerance)
    assert not b.same_object(a, last_modified_tolerance=tolerance)


def test_the_tolerance_cannot_be_widened_past_one_second_or_made_negative() -> None:
    assert objects_module.OPEN_LAST_MODIFIED_TOLERANCE == timedelta(seconds=1)
    a = identity(5)
    for bad in (timedelta(seconds=1, microseconds=1), timedelta(seconds=2), timedelta(seconds=-1)):
        with pytest.raises(ValueError):
            a.same_object(a, last_modified_tolerance=bad)


@pytest.mark.parametrize(
    ("a_ms", "b_ms", "accepted"),
    [
        (0, 1000, True),  # exactly one second
        (999, 1000, True),  # straddles a truncation boundary, 1 ms apart
        (1000, 0, True),
        (0, 1001, False),  # 1.001 s: over
        (0, 1999, False),  # truncation alone would have called this one second
        (1999, 0, False),
        (500, 1500, True),
    ],
)
def test_the_tolerance_is_one_real_second_not_one_truncated_second(
    a_ms: int, b_ms: int, accepted: bool
) -> None:
    a = identity(5, last_modified=STAMP + timedelta(milliseconds=a_ms))
    b = identity(5, last_modified=STAMP + timedelta(milliseconds=b_ms))
    assert a.same_object(b, last_modified_tolerance=timedelta(seconds=1)) is accepted
    assert b.same_object(a, last_modified_tolerance=timedelta(seconds=1)) is accepted


def test_the_tolerance_compares_across_utc_offsets() -> None:
    plus_two = (STAMP + timedelta(seconds=1)).astimezone(timezone(timedelta(hours=2)))
    assert identity(5).same_object(
        identity(5, last_modified=plus_two), last_modified_tolerance=timedelta(seconds=1)
    )


def test_the_default_comparison_is_still_exact() -> None:
    a = identity(5)
    assert not a.same_object(identity(5, last_modified=STAMP + timedelta(seconds=1)))


@pytest.mark.parametrize("drift", [1, -1, 2])
async def test_the_check_after_the_read_stays_exact_even_for_one_second(drift: int) -> None:
    """The tolerance is for HEAD vs GET. HEAD vs HEAD around the read gets none."""
    after = identity(len(BODY), last_modified=STAMP + timedelta(seconds=drift))
    source = FakeObjectSource(stats=[identity(len(BODY)), after], body=BODY)
    _, result, check = await run(source)
    assert result is not None and result.candidate_clean, "the read itself was accepted"
    assert check.gate is ObjectGate.CHANGED and not check.passed


async def test_a_post_read_etag_change_is_rejected_whatever_the_timestamp_did() -> None:
    after = identity(len(BODY), etag="etag-2")
    source = FakeObjectSource(
        stats=[identity(len(BODY)), after],
        open_identity=identity(len(BODY), last_modified=STAMP + timedelta(seconds=1)),
        body=BODY,
    )
    _, result, check = await run(source)
    assert result is not None and result.candidate_clean
    assert check.gate is ObjectGate.CHANGED and not check.passed


async def test_the_observed_one_second_head_get_drift_of_the_real_store_passes_end_to_end() -> None:
    """The DEV store's shape: HEAD and GET answer the same object, GET one second later.

    Real boto3 response shapes through `S3ObjectSource`, the real reader and the
    real check after the read (HEAD again, which carries the HEAD timestamp).
    """
    head = {"ContentLength": 5, "ETag": '"e1"', "LastModified": STAMP}
    get = {
        "ContentLength": 5,
        "ETag": '"e1"',
        "LastModified": STAMP + timedelta(seconds=1),
        "Body": StreamingBody(io.BytesIO(b"hello"), 5),
    }
    client = StrictClient(head=head, get=get)
    r = ObjectReader(S3ObjectSource(client, "b"), clock=lambda: ISSUED + timedelta(minutes=16))
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    assert (await FakeScanner.candidate_clean().scan(stream)).candidate_clean
    check = await r.verify(ref(), admission, stream)
    assert check.passed and stream.observed is not None
    assert stream.observed.last_modified != admission.identity.last_modified  # type: ignore[union-attr]


async def test_the_real_store_shape_two_seconds_apart_is_still_object_changed() -> None:
    head = {"ContentLength": 5, "ETag": '"e1"', "LastModified": STAMP}
    get = {
        "ContentLength": 5,
        "ETag": '"e1"',
        "LastModified": STAMP + timedelta(seconds=2),
        "Body": StreamingBody(io.BytesIO(b"hello"), 5),
    }
    r = ObjectReader(
        S3ObjectSource(StrictClient(head=head, get=get), "b"),
        clock=lambda: ISSUED + timedelta(minutes=16),
    )
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    result = await FakeScanner.candidate_clean().scan(stream)
    assert result.outcome is ScanOutcome.READ_FAILURE
    assert (await r.verify(ref(), admission, stream)).gate is ObjectGate.CHANGED


async def test_the_object_vanishing_after_the_read_is_not_a_pass() -> None:
    source = FakeObjectSource(stats=[identity(len(BODY)), None], body=BODY)
    check = (await run(source))[2]
    assert check.gate is ObjectGate.MISSING and not check.passed


async def test_the_store_going_away_after_the_read_is_not_a_pass() -> None:
    source = FakeObjectSource(stats=[identity(len(BODY)), ObjectSourceError("down")], body=BODY)
    check = (await run(source))[2]
    assert check.gate is ObjectGate.UNREACHABLE and not check.passed


async def test_an_object_replaced_between_inspection_and_open_is_caught_by_the_read_itself() -> (
    None
):
    source = FakeObjectSource(
        stats=[identity(len(BODY))],
        open_identity=identity(len(BODY), etag="swapped"),
        body=BODY,
    )
    admission, result, check = await run(source)
    assert result is not None and result.outcome is ScanOutcome.READ_FAILURE
    assert check.gate is ObjectGate.CHANGED and not check.passed
    assert sum(source.opened[0].requested) == 0, "nothing was read from the swapped object"


@pytest.mark.parametrize("served", [len(BODY) - 1, len(BODY) + 1, 0])
async def test_bytes_that_do_not_match_the_inspected_size_are_a_change(served: int) -> None:
    source = FakeObjectSource(stats=[identity(len(BODY))], body=BODY + b"extra", served=served)
    _, _, check = await run(source)
    assert check.gate is ObjectGate.CHANGED and not check.passed


async def test_a_read_that_fails_midway() -> None:
    source = FakeObjectSource(stats=[identity(len(BODY))], body=BODY, fail_after=40)
    _, result, check = await run(source)
    assert result is not None and result.outcome is ScanOutcome.READ_FAILURE
    assert check.gate is ObjectGate.UNREACHABLE and not check.passed
    assert source.opened[0].closed


async def test_an_object_that_disappears_between_inspection_and_open() -> None:
    source = FakeObjectSource(stats=[identity(len(BODY))], open_error=ObjectSourceError("gone"))
    _, result, check = await run(source)
    assert result is not None and result.outcome is ScanOutcome.READ_FAILURE
    assert check.gate is ObjectGate.UNREACHABLE and not check.passed


async def test_a_scanner_that_stops_early_cannot_pass_the_gate() -> None:
    source = source_for(b"z" * 100)
    _, result, check = await run(source, scanner=FirstChunkScanner(), chunk_bytes=10)
    assert result is not None and result.candidate_clean
    assert check.gate is ObjectGate.READ_INCOMPLETE and not check.passed


async def test_a_stream_is_single_use_and_only_an_admitted_object_can_be_streamed() -> None:
    source = source_for()
    r = reader(source)
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    async for _ in stream:
        pass
    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass
    for refused in (
        Admission(ObjectGate.WINDOW_NOT_ELAPSED),
        Admission(ObjectGate.MISSING),
        Admission(ObjectGate.OVERSIZED),
        Admission(ObjectGate.CHANGED),
    ):
        with pytest.raises(ValueError):
            r.stream(ref(), refused)
        with pytest.raises(ValueError):
            await r.verify(ref(), refused, stream)


# --- tenant, file and key: item 12 --------------------------------------------------


def test_a_matching_tenant_file_and_key_construct() -> None:
    assert ref().key == KEY
    # Keys written before the category segment existed stay readable.
    assert ObjectReference(TENANT, FILE, f"tenants/{TENANT}/{FILE}/a.pdf")
    assert ObjectReference(
        TENANT,
        FILE,
        f"tenants/{TENANT}/imports/{FILE}/My file (1).csv".replace("(", "").replace(")", ""),
    )


@pytest.mark.parametrize(
    "key",
    [
        f"tenants/{OTHER_TENANT}/documents/{FILE}/a.pdf",  # another tenant's object
        f"tenants/{TENANT}/documents/{OTHER_FILE}/a.pdf",  # another file's object
        f"tenants/{TENANT}/documents/{FILE}",  # no object name: the file id is the name
        f"tenants/{TENANT}/{FILE}",
        f"{TENANT}/documents/{FILE}/a.pdf",
        f"tenant/{TENANT}/documents/{FILE}/a.pdf",
        f"tenants/{TENANT}/documents/{FILE}/../{FILE}/a.pdf",
        f"tenants/{TENANT}/../{OTHER_TENANT}/documents/{FILE}/a.pdf",
        f"tenants/{TENANT}/documents//{FILE}/a.pdf",
        f"/tenants/{TENANT}/documents/{FILE}/a.pdf",
        f"tenants/{TENANT}/documents/{FILE}/a.pdf/",
        f"tenants\\{TENANT}\\documents\\{FILE}\\a.pdf",
        f"tenants/{TENANT}/documents/{FILE}/a\x00.pdf",
        f"tenants/{TENANT}/documents/{FILE}/a\n.pdf",
        f"tenants/{TENANT}/documents/{FILE}/a%2e%2e.pdf",
        "",
        "tenants",
    ],
)
def test_a_key_that_does_not_belong_to_the_tenant_and_file_is_refused(key: str) -> None:
    with pytest.raises(ObjectReferenceError):
        ObjectReference(TENANT, FILE, key)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        TENANT.replace("-", ""),
        f"{TENANT}/x",
    ],
)
def test_ids_must_be_canonical_uuids(bad: str) -> None:
    with pytest.raises(ObjectReferenceError):
        ObjectReference(bad, FILE, KEY)
    with pytest.raises(ObjectReferenceError):
        ObjectReference(TENANT, bad, KEY)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/tenants/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:3310/",
        "s3://other-bucket/tenants/x",
        "//evil.example/a",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_PING",
        f"tenants/{TENANT}/documents/{FILE}/http://evil.example/a.pdf",
    ],
)
def test_a_url_is_not_a_storage_key(url: str) -> None:
    with pytest.raises(ObjectReferenceError):
        ObjectReference(TENANT, FILE, url)


async def test_a_refused_reference_never_reaches_the_store() -> None:
    source = source_for()
    with pytest.raises(ObjectReferenceError):
        ObjectReference(TENANT, FILE, f"tenants/{OTHER_TENANT}/documents/{FILE}/a.pdf")
    assert source.calls == []


# --- no arbitrary URL, no signed URL, no credential: items 13 and security --------


def _params(fn: Any) -> set[str]:
    return {p for p in inspect.signature(fn).parameters if p != "self"}


def test_no_public_entry_point_takes_a_url_host_endpoint_or_credential() -> None:
    forbidden = re.compile(
        r"url|uri|host|endpoint|credential|secret|token|password|bucket|header", re.I
    )
    entry_points = [
        ObjectReader.__init__,
        ObjectReader.admit,
        ObjectReader.stream,
        ObjectReader.verify,
        scanning.ObjectStream.__init__,
        earliest_read,
        upload_window.earliest_scan_read,
        objects_module.ObjectSource.stat,
        objects_module.ObjectSource.open,
    ]
    for fn in entry_points:
        assert not [p for p in _params(fn) if forbidden.search(p)], fn
    assert _params(default_bucket_source) == {"settings"}
    for cls in (ObjectReference, ObjectIdentity, Admission, scanning.ObjectCheck):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not [n for n in names if forbidden.search(n)], cls
    assert {f.name for f in dataclasses.fields(ObjectReference)} == {"tenant_id", "file_id", "key"}


async def test_the_reader_cannot_be_given_a_url_in_place_of_a_reference() -> None:
    source = source_for()
    r = reader(source)
    admission = await r.admit(ref(), ISSUED)
    for call in (
        r.admit("https://evil.example/object", ISSUED),  # type: ignore[arg-type]
        r.verify("https://evil.example/object", admission, r.stream(ref(), admission)),  # type: ignore[arg-type]
    ):
        with pytest.raises(TypeError):
            await call
    with pytest.raises(TypeError):
        r.stream("https://evil.example/object", admission)  # type: ignore[arg-type]
    assert source.verbs == ["stat"], "only the legitimate admission reached the store"


def _module_sources() -> dict[str, str]:
    return {
        name: (SCANNING_DIR / name).read_text(encoding="utf-8") for name in ("objects.py", "s3.py")
    }


def _code(text: str) -> str:
    """The module as code only: no docstrings and no comments."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body[0] = ast.Pass()
    return ast.unparse(tree)


def test_the_modules_make_no_http_call_sign_nothing_and_hold_no_credential() -> None:
    for name, source in _module_sources().items():
        text = _code(source)
        imports = "\n".join(
            line for line in text.splitlines() if re.match(r"\s*(import|from)\s", line)
        )
        for module in (
            "httpx",
            "requests",
            "urllib",
            "aiohttp",
            "socket",
            "http",
            "os",
            "subprocess",
        ):
            assert not re.search(rf"^\s*(import|from)\s+{module}(\s|$|\.)", imports, re.M), (
                name,
                module,
            )
        for token in (
            "presign",
            "generate_presigned",
            "http://",
            "https://",
            "Authorization",
            "environ",
            "getenv",
        ):
            assert token not in text, (name, token)
        assert not re.search(r"access_key|secret_key|api_key|password", text, re.I), name


def test_the_modules_only_read() -> None:
    for name, source in _module_sources().items():
        text = _code(source)
        for call in (
            "put_object",
            "delete_object",
            "copy_object",
            "upload_file",
            "upload_part",
            "create_multipart",
            "restore_object",
            "put(",
            "delete(",
        ):
            assert call not in text, (name, call)
    s3 = _module_sources()["s3.py"]
    called = set(re.findall(r"self\._client\.(\w+)\(", s3))
    assert called == {"head_object", "get_object"}
    assert [n for n in dir(objects_module.ObjectSource) if not n.startswith("_")] == [
        "open",
        "stat",
    ]


def test_nothing_in_the_object_gate_touches_the_database_a_status_or_a_queue() -> None:
    for name, source in _module_sources().items():
        text = _code(source)
        for token in (
            "sqlalchemy",
            "scan_status",
            "record_scan",
            "quarantine",
            "redis",
            "koras_queue",
            "enqueue",
        ):
            assert token not in text.lower(), (name, token)
        assert not re.search(r"(insert|update|delete)\s+(into|public|from)", text, re.I), name
        assert not re.search(r"\bclean\b(?!_)", re.sub(r'"""[\s\S]*?"""', "", text)), name
        assert "skipped" not in re.sub(r'"""[\s\S]*?"""', "", text), name


def test_the_storage_dependency_is_confined_to_the_one_adapter_file() -> None:
    holders = [
        p.name
        for p in SCANNING_DIR.glob("*.py")
        if "koras_storage" in p.read_text(encoding="utf-8")
    ]
    assert holders == ["s3.py"]


def test_the_object_gate_is_reached_only_by_the_file_scan_task() -> None:
    """`tasks/scan.py` builds the reader and the S3 source; no other worker file may."""
    worker = SCANNING_DIR.parent
    naming = set()
    for path in worker.rglob("*.py"):
        if SCANNING_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if "scanning.objects" in text or "scanning.s3" in text:
            naming.add(path.relative_to(worker).as_posix())
    assert naming == {"tasks/scan.py"}


# --- ETag semantics: item 14 ------------------------------------------------------


@pytest.mark.parametrize(
    "etag",
    ["d41d8cd98f00b204e9800998ecf8427e", "ab" * 32, "d41d8cd98f00b204e9800998ecf8427e-12"],
)
def test_an_etag_never_populates_a_digest(etag: str) -> None:
    ident = identity(5, etag=etag, provider_sha256=None)
    assert ident.etag == etag
    assert ident.provider_sha256 is None
    assert ident.sufficient, "an ETag is sufficient identity evidence, and still no digest"


def test_the_etag_is_normalised_but_remains_opaque() -> None:
    assert identity(1, etag='"abc"').etag == "abc"
    assert identity(1, etag='W/"abc"').etag == "abc"
    assert identity(1, etag='""').etag is None


def test_no_code_path_derives_a_digest_from_an_etag() -> None:
    for name, source in _module_sources().items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.keyword) and node.arg == "provider_sha256":
                assert "etag" not in ast.dump(node.value).lower(), name
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and "sha256" in t.id for t in node.targets
            ):
                assert "etag" not in ast.dump(node.value).lower(), name
    text = _module_sources()["objects.py"]
    assert "not a content digest" in text and "never derived from the ETag" in text


# --- the S3 adapter ---------------------------------------------------------------


class StrictClient:
    """Answers only `head_object` and `get_object`; any other attribute is a failure."""

    def __init__(self, head: Any = None, get: Any = None) -> None:
        self.head, self.get, self.seen = head, get, []

    def head_object(self, **kwargs: Any) -> Any:
        self.seen.append(("head_object", kwargs))
        if isinstance(self.head, Exception):
            raise self.head
        return self.head

    def get_object(self, **kwargs: Any) -> Any:
        self.seen.append(("get_object", kwargs))
        if isinstance(self.get, Exception):
            raise self.get
        return self.get

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the reader called {name}")


def client_error(code: str, status: int = 400) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "op"
    )


def b64(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def test_head_maps_provider_metadata_to_distinct_evidence() -> None:
    client = StrictClient(
        head={
            "ContentLength": 7,
            "ETag": '"abc"',
            "LastModified": STAMP,
            "VersionId": "v9",
            "ChecksumSHA256": b64("ab" * 32),
        }
    )
    got = S3ObjectSource(client, "bucket").stat("k")
    assert got == ObjectIdentity(7, "abc", STAMP, "v9", "ab" * 32)
    assert client.seen == [
        ("head_object", {"Bucket": "bucket", "Key": "k", "ChecksumMode": "ENABLED"})
    ]


def test_a_composite_or_absent_provider_checksum_is_no_digest() -> None:
    for sha in ("YWJj-3", None, "not base64!!", b64("ab" * 16)):
        head = {"ContentLength": 1, "ETag": '"' + "cd" * 32 + '"', "LastModified": STAMP}
        if sha is not None:
            head["ChecksumSHA256"] = sha
        got = S3ObjectSource(StrictClient(head=head), "b").stat("k")
        assert got is not None and got.provider_sha256 is None
        assert got.etag == "cd" * 32


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_a_missing_key_is_none(code: str) -> None:
    assert S3ObjectSource(StrictClient(head=client_error(code, 404)), "b").stat("k") is None


@pytest.mark.parametrize(
    "error",
    [
        client_error("403", 403),
        client_error("InternalError", 500),
        EndpointConnectionError(endpoint_url="http://x"),
    ],
)
def test_any_other_failure_is_unreachable_and_never_missing(error: Exception) -> None:
    with pytest.raises(ObjectSourceError):
        S3ObjectSource(StrictClient(head=error), "b").stat("k")
    with pytest.raises(ObjectSourceError):
        S3ObjectSource(StrictClient(get=error), "b").open("k")


def test_the_read_carries_its_own_identity_and_streams_the_body() -> None:
    body = StreamingBody(io.BytesIO(b"abcdef"), 6)
    client = StrictClient(
        get={"ContentLength": 6, "ETag": '"q"', "LastModified": STAMP, "Body": body}
    )
    opened = S3ObjectSource(client, "b").open("k")
    assert opened.identity == ObjectIdentity(6, "q", STAMP)
    assert opened.read(4) == b"abcd" and opened.read(4) == b"ef" and opened.read(4) == b""
    opened.close()


async def test_the_adapter_end_to_end_through_the_reader() -> None:
    content = b"hello"
    head = {"ContentLength": 5, "ETag": '"e1"', "LastModified": STAMP}
    client = StrictClient(head=head, get={**head, "Body": StreamingBody(io.BytesIO(content), 5)})
    r = ObjectReader(S3ObjectSource(client, "b"), clock=lambda: ISSUED + timedelta(minutes=16))
    admission = await r.admit(ref(), ISSUED)
    stream = r.stream(ref(), admission)
    assert (await FakeScanner.candidate_clean().scan(stream)).candidate_clean
    assert (await r.verify(ref(), admission, stream)).passed
    assert {name for name, _ in client.seen} == {"head_object", "get_object"}


def test_the_calls_conform_to_the_real_s3_api_model() -> None:
    import boto3

    real = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
    )
    with Stubber(real) as stub:
        stub.add_response(
            "head_object",
            {"ContentLength": 3, "ETag": '"e"', "LastModified": STAMP},
            {"Bucket": "b", "Key": "k", "ChecksumMode": "ENABLED"},
        )
        stub.add_response(
            "get_object",
            {
                "ContentLength": 3,
                "ETag": '"e"',
                "LastModified": STAMP,
                "Body": StreamingBody(io.BytesIO(b"abc"), 3),
            },
            {"Bucket": "b", "Key": "k", "ChecksumMode": "ENABLED"},
        )
        source = S3ObjectSource(real, "b")
        assert source.stat("k") == ObjectIdentity(3, "e", STAMP)
        assert source.open("k").read(10) == b"abc"
        stub.assert_no_pending_responses()


def test_the_only_constructor_resolves_the_product_default_bucket() -> None:
    settings = StorageSettings(
        endpoint="http://storage.internal:9000",
        bucket="files-dev",
        region="us-east-1",
        access_key="k",
        secret_key="s",
    )
    source = default_bucket_source(settings)
    assert source._bucket == "files-dev"
    assert source._client.meta.endpoint_url == "http://storage.internal:9000"
    # The adapter reaches the vendored client through a private attribute; this
    # fails loudly if the vendored package moves it.
    assert hasattr(S3ObjectStore(resolve_destination(None, settings)), "_client")


# --- S1 semantics preserved: items 15 and 16 --------------------------------------


def test_s1_candidate_clean_semantics_are_unchanged() -> None:
    assert {o.value for o in ScanOutcome} == {
        "candidate_clean",
        "infected",
        "unavailable",
        "timeout",
        "malformed_response",
        "scanner_error",
        "limit_exceeded",
        "incomplete_inspection",
        "read_failure",
        "misconfigured",
    }
    assert {d.value for d in Disposition} == {
        "candidate_clean",
        "infected",
        "hold_retry",
        "hold_uninspectable",
    }
    ok = ScanResult(ScanOutcome.CANDIDATE_CLEAN)
    assert ok.candidate_clean and ok.requires_structural_gate and ok.failure is None
    assert ok.disposition is Disposition.CANDIDATE_CLEAN
    assert {f.value for f in ScanFailure} >= {
        "scanner_unavailable",
        "scan_timeout",
        "malformed_response",
        "scanner_error",
        "object_unreachable",
        "misconfigured",
        "scan_limit_exceeded",
        "inspection_incomplete",
    }


async def test_a_passing_object_gate_does_not_make_a_candidate_clean_into_anything_more() -> None:
    _, result, check = await run(source_for())
    assert check.passed
    assert result is not None and result.requires_structural_gate
    assert not hasattr(check, "clean") and not hasattr(check, "is_clean")
    assert not hasattr(check, "scan_status") and not hasattr(check, "disposition")
    assert "clean" not in {g.value for g in ObjectGate}
    assert "infected" not in {g.value for g in ObjectGate}
    assert "skipped" not in {g.value for g in ObjectGate}


async def test_an_infected_verdict_is_untouched_by_a_failed_object_gate() -> None:
    # The gate has no say over the scanner's answer; it only reports on the object.
    source = FakeObjectSource(stats=[identity(len(BODY)), identity(len(BODY), etag="x")], body=BODY)
    _, result, check = await run(source, scanner=FakeScanner.infected())
    assert result is not None and result.outcome is ScanOutcome.INFECTED
    assert check.gate is ObjectGate.CHANGED


def test_every_hold_is_a_hold_and_none_is_a_verdict() -> None:
    holds = [g for g in ObjectGate if g is not ObjectGate.READY]
    assert holds and not any(g.passed for g in holds)
    assert {g for g in holds if g.failure is None} == {ObjectGate.WINDOW_NOT_ELAPSED}


def test_there_is_no_status_transition_in_the_reader() -> None:
    # Nothing in the scanning package writes, imports or names a status column.
    for path in SCANNING_DIR.glob("*.py"):
        if path.name == "transition.py":  # the one guarded writer, tested on its own
            continue
        if path.name == "runtime.py":  # one read, no write; test_scan_runtime.py holds that
            continue
        text = path.read_text(encoding="utf-8")
        assert "scan_status" not in text, path.name
        assert "sqlalchemy" not in text, path.name
    # The scanner's schema is exactly the three migrations that follow the finalizer's
    # predecessor: the persistence columns, the thirteenth word with its first index, and the
    # due-time indexes.
    for number, name in (
        ("00039", "00039_file_scan_attempts.sql"),
        ("00040", "00040_file_scan_interrupted.sql"),
        ("00041", "00041_file_scan_due_indexes.sql"),
    ):
        assert [m.name for m in (REPO / "supabase/migrations").glob(f"{number}*")] == [name]
    # The task is named by the declaration, the sweep and the hand-off, and nowhere else.
    naming = {
        p.name
        for p in (SCANNING_DIR.parent / "tasks").glob("*.py")
        if "file.scan" in p.read_text(encoding="utf-8")
    }
    assert naming == {"scan.py", "scan_sweep.py"}
