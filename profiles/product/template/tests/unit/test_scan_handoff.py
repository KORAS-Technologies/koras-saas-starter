# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, S101
"""Finalization hands a final file to the scanner, and only a final file (`secure_files`).

No database, no queue server, no bucket: the finalizer's own behaviour is
`test_upload_finalization*.py` and the scanner's is `test_scan_runtime.py`. What is proved
here is the seam between them:

* the hand-off happens once the file is on its final key (finalized now, or found already
  final), after the swap's hold has been cleared, and in no other outcome;
* it is best effort: a queue that is down, a result that cannot be forgotten or an exception
  of any kind never turns a finalized file into a failure, and the file stays `pending`
  (withheld) for the scan sweep;
* what is enqueued is the one `file.scan` job, under its identity, for the file's own tenant;
* the sweep and the job both pass the hand-off, so a lost job is recovered the same way.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_api.core.scan_jobs import FILE_SCAN, scan_idempotency_key  # noqa: E402
from koras_queue import JobEnvelope, RecordingJobQueue, job_id_for  # noqa: E402
from koras_worker.tasks import finalize as finalize_task  # noqa: E402
from koras_worker.tasks import scan as scan_task  # noqa: E402
from koras_worker.uploads.finalize import (  # noqa: E402
    Finalization,
    FinalizeFailure,
    FinalizeKind,
)

TENANT = "00000000-0000-0000-0000-00000000000a"
FILE = "1111111a-1111-4111-8111-11111111111b"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class _Queue(RecordingJobQueue):
    closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Redis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


# ---------------------------------------------------------------- finalize_one -> on_final


@pytest.fixture
def finalizing(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`finalize_one` with the database edge replaced; records the order things happen in."""
    seen: dict[str, Any] = {"order": [], "outcome": Finalization(FinalizeKind.FINALIZED)}

    async def peek(session, tenant_id, file_id):
        return datetime(2026, 10, 6, 0, 0, tzinfo=UTC)

    async def count(session, tenant_id, file_id, now):
        return 1

    async def clear(session, tenant_id, file_id):
        seen["order"].append("clear")

    async def hold(session, tenant_id, file_id, failure):
        seen["order"].append("hold")

    monkeypatch.setattr(finalize_task, "_peek", peek)
    monkeypatch.setattr(finalize_task, "_count_attempt", count)
    monkeypatch.setattr(finalize_task, "_clear_hold", clear)
    monkeypatch.setattr(finalize_task, "_record_hold", hold)

    class Finalizer:
        async def finalize(self, session, *, tenant_id, file_id, now):
            return seen["outcome"]

    seen["finalizer"] = Finalizer()
    return seen


async def _run(seen: dict[str, Any], *, on_final, max_attempts: int = 8) -> dict[str, Any]:
    return await finalize_task.finalize_one(
        object(),
        seen["finalizer"],
        tenant_id=TENANT,
        file_id=FILE,
        now=NOW,
        max_attempts=max_attempts,
        on_final=on_final,
    )


@pytest.mark.parametrize("kind", [FinalizeKind.FINALIZED, FinalizeKind.ALREADY_FINAL])
async def test_a_file_that_is_final_is_handed_to_the_scanner_after_its_hold_is_cleared(
    finalizing, kind: FinalizeKind
) -> None:
    finalizing["outcome"] = Finalization(kind)

    async def on_final(tenant_id: str, file_id: str) -> None:
        finalizing["order"].append(("hand-off", tenant_id, file_id))

    summary = await _run(finalizing, on_final=on_final)
    assert summary["status"] == kind.value
    assert finalizing["order"] == ["clear", ("hand-off", TENANT, FILE)]


@pytest.mark.parametrize(
    "outcome",
    [
        Finalization(FinalizeKind.HELD, failure=FinalizeFailure.INTEGRITY_MISMATCH),
        Finalization(FinalizeKind.HELD, failure=FinalizeFailure.OBJECT_UNREACHABLE),
        Finalization(FinalizeKind.POSTPONED, opens_at=NOW),
        Finalization(FinalizeKind.NOT_ELIGIBLE),
    ],
    ids=["integrity", "unreachable", "deferred", "not-eligible"],
)
async def test_nothing_that_is_not_final_is_handed_over(finalizing, outcome: Finalization) -> None:
    finalizing["outcome"] = outcome
    calls: list[tuple[str, str]] = []

    async def on_final(tenant_id: str, file_id: str) -> None:
        calls.append((tenant_id, file_id))

    await _run(finalizing, on_final=on_final)
    assert calls == []


async def test_a_file_past_its_attempts_is_not_finalized_and_so_not_handed_over(finalizing) -> None:
    calls: list[tuple[str, str]] = []

    async def on_final(tenant_id: str, file_id: str) -> None:
        calls.append((tenant_id, file_id))

    summary = await _run(finalizing, on_final=on_final, max_attempts=0)
    assert summary["status"] == "exhausted" and calls == []


async def test_a_hand_off_that_raises_does_not_fail_a_finalized_file(finalizing, caplog) -> None:
    async def on_final(tenant_id: str, file_id: str) -> None:
        raise ConnectionError("redis is down: secret-value")

    caplog.set_level("ERROR")
    summary = await _run(finalizing, on_final=on_final)
    assert summary["status"] == "finalized"
    assert "ConnectionError" in caplog.text and "secret-value" not in caplog.text


async def test_without_a_hand_off_finalization_is_what_it_was(finalizing) -> None:
    summary = await _run(finalizing, on_final=None)
    assert summary == {"status": "finalized", "attempts": 1}


# ---------------------------------------------------------------- hand_off_to_scanner


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> _Queue:
    recorded = _Queue()
    monkeypatch.setattr(scan_task, "queue_for", lambda url: recorded)
    return recorded


async def test_the_hand_off_enqueues_one_scan_for_the_files_own_tenant(queue: _Queue) -> None:
    await scan_task.hand_off_to_scanner({}, TENANT, FILE)
    (job,) = queue.jobs
    assert job.task == "file.scan" and job.tenant_id == TENANT
    assert dict(job.payload) == {"file_id": FILE}
    assert job.idempotency_key == scan_idempotency_key(FILE)
    assert queue.closed, "the connection the hand-off opened is closed"


async def test_a_retained_result_for_the_same_identity_is_forgotten_first(queue: _Queue) -> None:
    redis = _Redis()
    await scan_task.hand_off_to_scanner({"redis": redis}, TENANT, FILE)
    expected = job_id_for(FILE_SCAN, TENANT, scan_idempotency_key(FILE))
    assert len(redis.deleted) == 1 and redis.deleted[0].endswith(expected)
    assert len(queue.jobs) == 1


async def test_the_hand_off_never_raises_when_the_queue_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    def broken(url: str) -> Any:
        raise OSError("no route to redis://:secret-value@host")

    monkeypatch.setattr(scan_task, "queue_for", broken)
    caplog.set_level("ERROR")
    assert await scan_task.hand_off_to_scanner({}, TENANT, FILE) is False
    assert "OSError" in caplog.text and "secret-value" not in caplog.text
    assert "the sweep will recover it" in caplog.text


async def test_the_hand_off_never_raises_when_the_enqueue_fails(queue: _Queue) -> None:
    async def broken(task, **kwargs):
        raise ConnectionError("redis")

    queue.enqueue = broken  # type: ignore[method-assign]
    assert await scan_task.hand_off_to_scanner({}, TENANT, FILE) is False
    assert queue.closed


async def test_the_hand_off_never_raises_when_the_result_cannot_be_forgotten(queue: _Queue) -> None:
    class Broken:
        async def delete(self, key: str) -> None:
            raise ConnectionError("redis")

    assert await scan_task.hand_off_to_scanner({"redis": Broken()}, TENANT, FILE) is False


async def test_a_malformed_id_is_refused_without_touching_the_queue(queue: _Queue) -> None:
    assert await scan_task.hand_off_to_scanner({}, TENANT, "not-a-uuid") is False
    assert queue.jobs == []


# ------------------------------------------------- the job and the sweep both pass it


async def test_the_finalize_job_passes_the_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_finalize_one(session, finalizer, **kwargs):
        seen.update(kwargs)
        return {"status": "finalized", "attempts": 1}

    class Engine:
        async def dispose(self) -> None:
            return None

    class Opened:
        async def __aenter__(self) -> str:
            return "session"

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(finalize_task, "finalize_one", fake_finalize_one)
    monkeypatch.setattr(finalize_task, "_engine", lambda: Engine())
    monkeypatch.setattr(finalize_task, "async_sessionmaker", lambda *a, **k: lambda: Opened())
    monkeypatch.setattr(finalize_task.settings, "database_url", "postgresql://u:p@h/db")
    handed: list[tuple[str, str, dict[str, Any]]] = []

    async def hand_off(ctx, tenant_id, file_id):
        handed.append((tenant_id, file_id, ctx))
        return True

    monkeypatch.setattr(scan_task, "hand_off_to_scanner", hand_off)
    ctx: dict[str, Any] = {"redis": object()}
    envelope = JobEnvelope(
        task="file.finalize",
        tenant_id=TENANT,
        payload={"file_id": FILE},
        idempotency_key=f"finalize:{FILE}",
    )
    await finalize_task.finalize_file_task(ctx, envelope)
    assert callable(seen["on_final"])
    await seen["on_final"](TENANT, FILE)
    assert handed == [(TENANT, FILE, ctx)]


async def test_the_finalize_sweep_passes_the_hand_off_too(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs_seen: list[dict[str, Any]] = []

    async def fake_finalize_one(session, finalizer, **kwargs):
        kwargs_seen.append(kwargs)
        return {"status": "finalized"}

    class Result:
        def mappings(self) -> Any:
            return SimpleNamespace(all=lambda: [{"id": FILE, "tenant_id": TENANT}])

    class Session:
        async def execute(self, *args: object, **kwargs: object) -> Result:
            return Result()

        async def rollback(self) -> None:
            return None

    class Opened:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *exc: object) -> None:
            return None

    class Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(finalize_task, "finalize_one", fake_finalize_one)
    monkeypatch.setattr(finalize_task, "_engine", lambda: Engine())
    monkeypatch.setattr(finalize_task, "async_sessionmaker", lambda *a, **k: lambda: Opened())
    monkeypatch.setattr(finalize_task.settings, "database_url", "postgresql://u:p@h/db")
    result = await finalize_task.sweep_finalize({"redis": object()})
    assert result["considered"] == 1
    assert callable(kwargs_seen[0]["on_final"])


# --------------------------------------------------------------- what the hand-off is not


def test_the_hand_off_is_not_a_trust_decision() -> None:
    """It names a file and a tenant. It carries no key, no digest and no verdict."""
    import inspect

    source = inspect.getsource(scan_task.hand_off_to_scanner)
    for forbidden in ("storage_key", "checksum", "scan_status", "clean", "presign"):
        assert forbidden not in source, forbidden
