"""The `file.finalize` job and its sweep: what they accept, what they record, what they refuse.

No database and no bucket: the finalizer's own behaviour is `test_upload_finalization_real.py`.
This is the edge around it (ADR 0013, `secure_files`):

* a job carries one canonical file id on a canonical tenant's envelope, and nothing else;
* every attempt is counted before anything is read, and a refusal is recorded as a closed
  word and never as a release;
* the sweep selects only files that are confirmed, unverified and still on a key a client could
  write, only after the window, never one whose bytes were found not to be the claim, and with
  a bounded retry -- and it is registered in the worker beside the job.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_api.core import finalize_jobs  # noqa: E402
from koras_api.core.upload_window import FINALIZE_DELAY_SECONDS  # noqa: E402
from koras_queue import JobEnvelope  # noqa: E402
from koras_worker.tasks import finalize as task  # noqa: E402
from koras_worker.uploads.finalize import (  # noqa: E402
    Finalization,
    FinalizeFailure,
    FinalizeKind,
    FinalizeStoreUnavailable,
)

TENANT = "00000000-0000-0000-0000-00000000000a"
FILE = "1111111a-1111-4111-8111-11111111111b"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def envelope(**overrides: Any) -> JobEnvelope:  # noqa: ANN401
    values: dict[str, Any] = {
        "task": "file.finalize",
        "tenant_id": TENANT,
        "payload": {"file_id": FILE},
        "idempotency_key": f"finalize:{FILE}",
    }
    values.update(overrides)
    return JobEnvelope(**values)


# --- the declaration -------------------------------------------------------------------------


def test_the_declaration_is_one_attempt_with_a_timeout_for_the_largest_object() -> None:
    definition = finalize_jobs.FILE_FINALIZE
    assert definition.name == "file.finalize"
    assert definition.retry.attempts == 1, "a retry is the sweep's, with a back-off"
    assert definition.timeout_seconds >= 1800


def test_the_job_identity_and_payload_are_one_canonical_file_id() -> None:
    assert finalize_jobs.finalize_idempotency_key(FILE) == f"finalize:{FILE}"
    assert finalize_jobs.finalize_payload(FILE) == {"file_id": FILE}
    for bad in ("", "x", FILE.upper(), "../x", FILE + "0"):
        with pytest.raises(ValueError):
            finalize_jobs.finalize_idempotency_key(bad)
        with pytest.raises(ValueError):
            finalize_jobs.finalize_payload(bad)


# --- a job is validated before anything is read ----------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"tenant_id": "not-a-uuid"},
        {"tenant_id": TENANT.upper()},
        {"payload": {}},
        {"payload": {"file_id": FILE, "object": "tenants/x/incoming/y"}},
        {"payload": {"file_id": FILE, "bucket": "other"}},
        {"payload": {"file_id": "not-a-uuid"}},
        {"payload": {"file_id": FILE.upper()}},
        {"idempotency_key": "finalize:" + str(uuid.uuid4())},
    ],
)
async def test_a_malformed_job_is_refused_with_no_read_and_no_write(
    bad: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never(*args: object, **kwargs: object) -> object:
        raise AssertionError("a refused job touched the database")

    monkeypatch.setattr(task, "finalize_one", never)
    monkeypatch.setattr(task, "_engine", never)
    refused = await task.finalize_file_task({}, envelope(**bad))
    assert refused["status"] == "refused"


def test_the_queue_itself_refuses_a_payload_key_named_like_a_credential() -> None:
    from koras_queue.queue import PayloadRefused

    with pytest.raises(PayloadRefused):
        envelope(payload={"file_id": FILE, "key": "tenants/x/incoming/y"})
    with pytest.raises(PayloadRefused):
        envelope(payload={"file_id": FILE, "secret": "x"})


async def test_a_worker_with_no_database_skips_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task.settings, "database_url", "")
    result = await task.finalize_file_task({}, envelope())
    assert result == {"status": "skipped", "reason": "no database"}


# --- one attempt ------------------------------------------------------------------------------


class _Finalizer:
    def __init__(self, outcome: Finalization) -> None:
        self.outcome = outcome
        self.calls = 0

    async def finalize(self, session: object, **kwargs: object) -> Finalization:
        self.calls += 1
        return self.outcome


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"count": [], "hold": [], "clear": []}
    attempts = {"n": 0}

    async def peek(session: object, tenant: str, file: str) -> datetime:
        return NOW - timedelta(days=1)  # a ticket whose window closed long ago

    async def count(session: object, tenant: str, file: str, now: datetime) -> int | None:
        seen["count"].append((tenant, file, now))
        attempts["n"] += 1
        return attempts["n"] if attempts["n"] > 0 else None

    async def hold(session: object, tenant: str, file: str, failure: FinalizeFailure) -> None:
        seen["hold"].append((tenant, file, failure))

    async def clear(session: object, tenant: str, file: str) -> None:
        seen["clear"].append((tenant, file))

    monkeypatch.setattr(task, "_peek", peek)
    monkeypatch.setattr(task, "_count_attempt", count)
    monkeypatch.setattr(task, "_record_hold", hold)
    monkeypatch.setattr(task, "_clear_hold", clear)
    return seen


async def _one(finalizer: _Finalizer, max_attempts: int = 8) -> dict[str, Any]:
    return await task.finalize_one(
        object(),
        finalizer,  # type: ignore[arg-type]
        tenant_id=TENANT,
        file_id=FILE,
        now=NOW,
        max_attempts=max_attempts,
    )


async def test_an_attempt_is_counted_before_the_finalizer_runs(
    recorded: dict[str, list[Any]],
) -> None:
    finalizer = _Finalizer(Finalization(FinalizeKind.FINALIZED, key="k"))
    result = await _one(finalizer)
    assert result == {"status": "finalized", "attempts": 1}
    assert recorded["count"] == [(TENANT, FILE, NOW)] and finalizer.calls == 1
    assert recorded["clear"] == [(TENANT, FILE)], "a finalized file no longer carries an old hold"
    assert recorded["hold"] == []


@pytest.mark.parametrize("failure", list(FinalizeFailure))
async def test_a_refusal_is_recorded_as_its_closed_word_and_nothing_else(
    recorded: dict[str, list[Any]], failure: FinalizeFailure
) -> None:
    result = await _one(_Finalizer(Finalization(FinalizeKind.HELD, failure=failure)))
    assert result == {"status": "held", "attempts": 1, "failure": failure.value}
    assert recorded["hold"] == [(TENANT, FILE, failure)]
    assert recorded["clear"] == []


async def test_a_refusal_with_no_word_is_recorded_as_unreachable_never_as_success(
    recorded: dict[str, list[Any]],
) -> None:
    result = await _one(_Finalizer(Finalization(FinalizeKind.HELD)))
    assert result["failure"] == "object_unreachable"
    assert recorded["hold"] == [(TENANT, FILE, FinalizeFailure.OBJECT_UNREACHABLE)]


async def test_a_file_whose_window_has_not_closed_is_deferred_and_not_counted(
    recorded: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fresh(session: object, tenant: str, file: str) -> datetime:
        return NOW - timedelta(minutes=1)

    monkeypatch.setattr(task, "_peek", fresh)
    finalizer = _Finalizer(Finalization(FinalizeKind.FINALIZED, key="k"))
    result = await _one(finalizer)
    expected = (NOW - timedelta(minutes=1) + timedelta(seconds=FINALIZE_DELAY_SECONDS)).isoformat()
    assert result == {"status": "deferred", "opens_at": expected}
    assert recorded["count"] == [] and finalizer.calls == 0, "a deferral is not an attempt"


async def test_the_finalizers_own_deferral_is_reported_and_records_nothing(
    recorded: dict[str, list[Any]],
) -> None:
    opens = NOW + timedelta(minutes=3)
    result = await _one(_Finalizer(Finalization(FinalizeKind.POSTPONED, opens_at=opens)))
    assert result["status"] == "deferred" and result["opens_at"] == opens.isoformat()
    assert recorded["hold"] == [] and recorded["clear"] == []


async def test_a_file_past_its_attempts_is_not_finalized_again(
    recorded: dict[str, list[Any]],
) -> None:
    finalizer = _Finalizer(Finalization(FinalizeKind.FINALIZED, key="k"))
    result = await _one(finalizer, max_attempts=0)
    assert result == {"status": "exhausted", "attempts": 1}
    assert finalizer.calls == 0, "an exhausted file waits for a person"


async def test_a_file_that_is_no_longer_eligible_is_not_finalized(
    recorded: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def gone(session: object, tenant: str, file: str) -> None:
        return None

    monkeypatch.setattr(task, "_peek", gone)
    finalizer = _Finalizer(Finalization(FinalizeKind.FINALIZED, key="k"))
    assert (await _one(finalizer))["status"] == "not_eligible" and finalizer.calls == 0
    assert recorded["count"] == []


async def test_a_file_that_vanishes_between_the_peek_and_the_count_is_not_finalized(
    recorded: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def vanished(session: object, tenant: str, file: str, now: datetime) -> None:
        return None

    monkeypatch.setattr(task, "_count_attempt", vanished)
    finalizer = _Finalizer(Finalization(FinalizeKind.FINALIZED, key="k"))
    assert (await _one(finalizer))["status"] == "not_eligible" and finalizer.calls == 0


# --- no object store means nothing is finalized -----------------------------------------------


def test_with_no_object_store_configured_the_store_refuses_rather_than_pretends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY"):
        monkeypatch.setenv(name, "")
    store = task._LazyFinalizeStore()
    with pytest.raises(FinalizeStoreUnavailable):
        store.head("tenants/x")
    with pytest.raises(FinalizeStoreUnavailable):
        store.sha256("tenants/x")


# --- the sweep ---------------------------------------------------------------------------------


def _sql() -> str:
    return " ".join(str(task._DUE).split())


def test_the_sweep_selects_only_unverified_confirmed_files_on_a_client_writable_key() -> None:
    sql = _sql()
    assert "status = 'ready' and scan_status = 'pending'" in sql
    assert "position('/incoming/' in storage_key) > 0" in sql
    assert "created_at <= :due_before" in sql
    assert "scan_attempts < :max_attempts" in sql


def test_the_sweep_never_selects_a_digest_that_was_not_the_claim() -> None:
    sql = _sql()
    assert "scan_failure <> 'integrity_mismatch'" in sql
    assert "scan_attempted_at <= :retry_before" in sql, "every other reason waits out a back-off"


def test_the_sweep_reads_ids_and_nothing_else() -> None:
    assert _sql().startswith("select id, tenant_id from public.files")


def test_the_sweeps_window_is_the_finalization_horizon_not_a_setting() -> None:
    settings_fields = set(task.FinalizeSettings.model_fields)
    assert not {name for name in settings_fields if "delay" in name or "window" in name}
    assert FINALIZE_DELAY_SECONDS >= 19 * 60


def test_the_sweeps_knobs_are_bounded() -> None:
    fields = task.FinalizeSettings.model_fields
    for name in (
        "file_finalize_sweep_batch",
        "file_finalize_retry_seconds",
        "file_finalize_max_attempts",
    ):
        metadata = {type(m).__name__ for m in fields[name].metadata}
        assert {"Ge", "Le"} <= metadata, f"{name} must have a floor and a ceiling"
    with pytest.raises(ValueError):
        task.FinalizeSettings(file_finalize_max_attempts=0)
    with pytest.raises(ValueError):
        task.FinalizeSettings(file_finalize_sweep_batch=10_000)


def test_a_blank_knob_means_the_default_not_an_error() -> None:
    config = task.FinalizeSettings(file_finalize_sweep_batch="")  # type: ignore[arg-type]
    assert config.file_finalize_sweep_batch == 25


async def test_the_sweep_with_no_database_skips_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task.settings, "database_url", "")
    assert await task.sweep_finalize({}) == {"status": "skipped", "reason": "no database"}


# --- the worker registers both ----------------------------------------------------------------


def test_the_worker_binds_the_job_by_name_and_schedules_the_sweep() -> None:
    from koras_worker import worker

    names = {getattr(function, "name", None) for function in worker.WorkerSettings.functions}
    assert "file.finalize" in names
    jobs = {getattr(job, "name", None) for job in worker.WorkerSettings.cron_jobs}
    assert "cron:sweep_finalize" in jobs or any("sweep_finalize" in str(j) for j in jobs)


def test_the_bound_task_is_the_declared_one() -> None:
    (bound,) = task.bound()
    assert bound.definition is finalize_jobs.FILE_FINALIZE
    assert SimpleNamespace(name=bound.name).name == "file.finalize"
