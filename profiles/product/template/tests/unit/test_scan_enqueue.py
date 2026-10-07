# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN204, ANN401, E501, S101, S608
"""`secure_files`: a finalized file is enqueued for scanning, and only that.

What is proved: the job carries exactly `{"file_id": <uuid>}` on the tenant's
envelope under `scan:<file_id>`; no URL, token, key or credential can be in it; a queue
fault neither raises nor writes anything to the file; and a duplicate enqueue collapses.
The upload window the scanner may not read inside is a constant of `upload_window`, and the
finalizer's delay is longer than it. Deterministic: the queue is the recording one.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.scan_enqueue import enqueue_scan  # noqa: E402
from koras_api.core.scan_jobs import FILE_SCAN, scan_idempotency_key  # noqa: E402
from koras_api.core.upload_window import (  # noqa: E402
    SCAN_READ_DELAY_SECONDS,
    UPLOAD_SAFETY_MARGIN_SECONDS,
    UPLOAD_URL_SECONDS,
)
from koras_queue import RecordingJobQueue, job_id_for  # noqa: E402

TENANT = "11111111-1111-4111-8111-111111111111"
FILE = "33333333-3333-4333-8333-333333333333"


class BrokenQueue(RecordingJobQueue):
    async def enqueue(self, task, **kwargs):
        raise ConnectionError("redis is not there")


# ------------------------------------------------------------------ the job itself


async def test_the_job_is_exactly_the_file_id_under_scan_colon_file_id() -> None:
    queue = RecordingJobQueue()
    result = await enqueue_scan(queue, tenant_id=TENANT, file_id=FILE)
    assert result is not None
    (job,) = queue.jobs
    assert job.task == "file.scan"
    assert job.tenant_id == TENANT
    assert dict(job.payload) == {"file_id": FILE}
    assert job.idempotency_key == f"scan:{FILE}" == scan_idempotency_key(FILE)
    assert result.job_id == job_id_for(FILE_SCAN, TENANT, f"scan:{FILE}")


async def test_the_job_carries_no_url_token_key_host_or_credential() -> None:
    queue = RecordingJobQueue()
    await enqueue_scan(queue, tenant_id=TENANT, file_id=FILE)
    wire = str(queue.jobs[0].as_dict()).lower()
    for forbidden in ("http", "://", "token", "secret", "password", "credential", "bucket", "amz"):
        assert forbidden not in wire
    assert set(queue.jobs[0].payload) == {"file_id"}


@pytest.mark.parametrize(
    "bad", ["", "not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", FILE + "/../x", "../" + FILE]
)
async def test_a_file_id_that_is_not_a_canonical_uuid_is_refused_before_the_queue(bad: str) -> None:
    queue = RecordingJobQueue()
    with pytest.raises(ValueError):
        await enqueue_scan(queue, tenant_id=TENANT, file_id=bad)
    assert queue.jobs == []


async def test_a_blank_tenant_is_refused_by_the_queue_envelope() -> None:
    queue = RecordingJobQueue()
    # The failure is swallowed (the sweep recovers), but nothing is enqueued.
    assert (
        await enqueue_scan(queue, tenant_id=" ", file_id=FILE)
        is None
    )
    assert queue.jobs == []


async def test_two_enqueues_of_one_file_share_one_job_identity() -> None:
    queue = RecordingJobQueue()
    first = await enqueue_scan(queue, tenant_id=TENANT, file_id=FILE)
    second = await enqueue_scan(
        queue, tenant_id=TENANT, file_id=FILE
    )
    assert first is not None and second is not None and first.job_id == second.job_id


async def test_the_same_file_id_under_two_tenants_never_shares_a_job_id() -> None:
    other = "22222222-2222-4222-8222-222222222222"
    assert job_id_for(FILE_SCAN, TENANT, f"scan:{FILE}") != job_id_for(
        FILE_SCAN, other, f"scan:{FILE}"
    )


# ----------------------------------------------------- the upload window is preserved


def test_the_window_is_fifteen_minutes_plus_a_fixed_sixty_seconds() -> None:
    assert UPLOAD_URL_SECONDS == 15 * 60
    assert UPLOAD_SAFETY_MARGIN_SECONDS == 60
    assert SCAN_READ_DELAY_SECONDS == 16 * 60


def test_the_finalization_delay_is_the_window_plus_the_measured_in_flight_bound_plus_the_margin() -> None:
    from koras_api.core.upload_window import FINALIZE_DELAY_SECONDS, IN_FLIGHT_BOUND_SECONDS

    # 150 s is what the provider was measured to allow; the constant rounds it up.
    assert IN_FLIGHT_BOUND_SECONDS >= 150
    assert FINALIZE_DELAY_SECONDS == 15 * 60 + IN_FLIGHT_BOUND_SECONDS + 60
    # So by the time a file is on a final key, the scanner's own read gate is already open.
    assert FINALIZE_DELAY_SECONDS > SCAN_READ_DELAY_SECONDS


async def test_a_finalized_file_is_enqueued_for_now_and_not_deferred() -> None:
    queue = RecordingJobQueue()
    await enqueue_scan(queue, tenant_id=TENANT, file_id=FILE)
    (job,) = queue.jobs
    assert getattr(job, "delay_seconds", None) in (None, 0, 0.0)


# --------------------------------------------------- an enqueue failure is not an upload's


async def test_a_queue_failure_is_swallowed_and_nothing_is_raised() -> None:
    assert (
        await enqueue_scan(
            BrokenQueue(), tenant_id=TENANT, file_id=FILE
        )
        is None
    )


async def test_the_failure_log_names_the_error_class_and_no_message(caplog) -> None:
    caplog.set_level("ERROR")
    await enqueue_scan(BrokenQueue(), tenant_id=TENANT, file_id=FILE)
    text = caplog.text
    assert "ConnectionError" in text and "redis is not there" not in text


# ------------------------------------------------ only a key the finalizer wrote is scannable


@pytest.mark.parametrize(
    "key,final",
    [
        (f"tenants/{TENANT}/documents/{FILE}/final/{FILE}/a.csv", True),
        (f"tenants/{TENANT}/documents/{FILE}/incoming/{FILE}/a.csv", False),
        (f"tenants/{TENANT}/documents/{FILE}/a.csv", False),
        (f"tenants/{TENANT}/documents/{FILE}/final/not-a-uuid/a.csv", False),
        (f"tenants/{TENANT}/documents/{FILE}/final/{FILE}/a.csv/extra", False),
        (f"tenants/{TENANT}/documents/{FILE}/final//a.csv", False),
        ("", False),
    ],
)
def test_only_the_exact_final_key_shape_is_final(key: str, final: bool) -> None:
    from koras_api.core.upload_window import is_final_key

    assert is_final_key(key) is final


def test_a_key_the_finalizer_writes_is_a_final_key() -> None:
    from koras_api.core.upload_window import (
        final_key_for,
        incoming_key,
        is_final_key,
        is_incoming_key,
    )

    incoming = incoming_key(TENANT, "documents", FILE, FILE, "a.csv")
    final = final_key_for(incoming, FILE)
    assert is_final_key(final) and not is_incoming_key(final)
    assert not is_final_key(incoming) and is_incoming_key(incoming)
