# ruff: noqa: ANN001, ANN201, ANN401, E501, S101
"""The `file.scan` task's registration, its edge and its triggers (`secure_files`).

`test_scan_runtime.py` proves what a run does. This proves what a *job* may say,
that the task is bound the way the worker binds everything, that the attempt
threshold reaches the transitions from the one place it is configured, and the
other half of the boundary: that exactly the finalizer and the sweep start it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_api.core import scan_jobs  # noqa: E402
from koras_queue import (  # noqa: E402
    BoundTask,
    JobEnvelope,
    PayloadRefused,
    RecordingJobQueue,
    job_id_for,
    worker_functions,
)
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import ScanDisposition, ScanFailure, ScanRun  # noqa: E402
from koras_worker.scanning.config import ScannerSettings  # noqa: E402
from koras_worker.tasks import scan  # noqa: E402
from object_support import FILE, OTHER_TENANT, TENANT  # noqa: E402

REPO = Path(scanning.__file__).parents[4]
WORKER = REPO / "services" / "worker" / "koras_worker"


def envelope(**overrides: Any) -> JobEnvelope:
    values: dict[str, Any] = {
        "task": "file.scan",
        "tenant_id": TENANT,
        "payload": {"file_id": FILE},
        "idempotency_key": f"scan:{FILE}",
    }
    values.update(overrides)
    return JobEnvelope(**values)


# =========================================================================================
# Registration
# =========================================================================================


def test_file_scan_is_bound_by_the_scan_module_and_registered_in_the_worker() -> None:
    (bound,) = scan.bound()
    assert isinstance(bound, BoundTask)
    assert bound.definition is scan_jobs.FILE_SCAN
    assert bound.handler is scan.scan_file_task
    worker = (WORKER / "worker.py").read_text(encoding="utf-8")
    assert "*worker_functions(scan_tasks())" in worker, "bound by name, in the one list"


def test_the_worker_builds_a_function_for_it_with_the_declared_policy() -> None:
    (built,) = worker_functions(scan.bound())
    assert built.name == "file.scan"
    assert built.max_tries == 1
    assert built.timeout_s == scan_jobs.SCAN_TIMEOUT_SECONDS


def test_it_is_tried_once_because_retrying_is_the_sweeps_job() -> None:
    assert scan_jobs.FILE_SCAN.retry.attempts == 1


def test_the_queue_timeout_outlasts_the_scanners_own_longest_wall_clock() -> None:
    longest = ScannerSettings.model_fields["file_scan_timeout_seconds"]
    ceiling = next(m.le for m in longest.metadata if hasattr(m, "le"))
    assert scan_jobs.SCAN_TIMEOUT_SECONDS > ceiling
    assert scan_jobs.SCAN_TIMEOUT_SECONDS > longest.default


def test_no_second_queue_worker_or_service_was_added() -> None:
    assert not list(WORKER.rglob("*scan*worker*"))
    services = sorted(p.name for p in (REPO / "services").iterdir() if p.is_dir())
    assert "scanner" not in services and "clamd" in services, "the engine is the clamd service"
    assert [t.name for t in scan.bound()].count("file.scan") == 1


# =========================================================================================
# What a job may carry
# =========================================================================================


def test_the_canonical_job_identity_is_scan_colon_file_id() -> None:
    assert scan_jobs.scan_idempotency_key(FILE) == f"scan:{FILE}"
    assert scan_jobs.scan_payload(FILE) == {"file_id": FILE}


def test_the_queue_collapses_duplicates_per_tenant_and_file() -> None:
    key = scan_jobs.scan_idempotency_key(FILE)
    first = job_id_for(scan_jobs.FILE_SCAN, TENANT, key)
    assert first == job_id_for(scan_jobs.FILE_SCAN, TENANT, key)
    assert first != job_id_for(scan_jobs.FILE_SCAN, OTHER_TENANT, key)
    assert first.startswith("file.scan:")


@pytest.mark.parametrize("bad", ["", "x", FILE.replace("-", ""), "{" + FILE + "}", FILE + " "])
def test_the_declaration_refuses_anything_but_a_canonical_file_id(bad: str) -> None:
    with pytest.raises(ValueError, match="canonical UUID"):
        scan_jobs.scan_payload(bad)
    with pytest.raises(ValueError, match="canonical UUID"):
        scan_jobs.scan_idempotency_key(bad)


async def test_a_real_enqueue_carries_the_tenant_and_one_identifier_and_nothing_else() -> None:
    queue = RecordingJobQueue()
    queued = await queue.enqueue(
        scan_jobs.FILE_SCAN,
        tenant_id=TENANT,
        payload=scan_jobs.scan_payload(FILE),
        idempotency_key=scan_jobs.scan_idempotency_key(FILE),
    )
    (sent,) = queue.jobs
    wire = sent.as_dict()
    assert wire["payload"] == {"file_id": FILE}
    assert queued.job_id == job_id_for(scan_jobs.FILE_SCAN, TENANT, f"scan:{FILE}")
    flat = repr(wire).lower()
    for forbidden in ("http", "amazonaws", "signature", "x-amz", "secret", "token", "bucket"):
        assert forbidden not in flat, forbidden


@pytest.mark.parametrize("name", ["storage_key", "signed_token", "access_secret", "password"])
def test_the_queue_itself_refuses_a_payload_named_like_a_credential(name: str) -> None:
    with pytest.raises(PayloadRefused):
        envelope(payload={"file_id": FILE, name: "x"})


# =========================================================================================
# The handler refuses what it should and wires what it should
# =========================================================================================


class _Engine:
    disposed = False

    async def dispose(self) -> None:
        _Engine.disposed = True


class _Opened:
    async def __aenter__(self) -> str:
        return "session"

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The handler with its three collaborators replaced; records what `scan_file` receives."""
    seen: dict[str, Any] = {"calls": []}

    async def fake_scan_file(session: Any, **kwargs: Any) -> ScanRun:
        seen["calls"].append({"session": session, **kwargs})
        return ScanRun(ScanDisposition.CLEAN, attempts=1)

    monkeypatch.setattr(scan, "scan_file", fake_scan_file)
    monkeypatch.setattr(scan, "_engine", lambda: _Engine())
    monkeypatch.setattr(scan, "async_sessionmaker", lambda *a, **k: lambda: _Opened())
    monkeypatch.setattr(scan.settings, "database_url", "postgresql://u:p@h/db")
    _Engine.disposed = False
    return seen


async def test_a_valid_job_runs_one_scan_for_the_envelopes_tenant(wired) -> None:
    result = await scan.scan_file_task({}, envelope())
    assert result == {"status": "clean", "attempts": 1}
    (call,) = wired["calls"]
    assert (call["tenant_id"], call["file_id"]) == (TENANT, FILE)
    assert call["now"].tzinfo is not None
    assert _Engine.disposed


@pytest.mark.parametrize(
    "overrides",
    [
        {"payload": {}},
        {"payload": {"file_id": FILE, "bucket": "other"}},
        {"payload": {"file_id": FILE, "url": "https://evil.example/x"}},
        {"payload": {"file_id": FILE, "tenant_id": OTHER_TENANT}},
        {"payload": {"file_id": "not-a-uuid"}},
        {"payload": {"file_id": 7}},
        {"payload": {"file_id": f"{FILE} "}},
        {"payload": {"id": FILE}},
        {"tenant_id": "not-a-uuid"},
        {"tenant_id": TENANT.upper().replace("1", "A")},
        {"idempotency_key": "scan:44444444-4444-4444-8444-444444444444"},
        {"idempotency_key": f"file.scan:{FILE}"},
    ],
)
async def test_a_job_that_says_more_or_other_than_one_file_id_is_refused_untouched(
    wired, overrides: dict[str, Any]
) -> None:
    result = await scan.scan_file_task({}, envelope(**overrides))
    assert result["status"] == "refused"
    assert wired["calls"] == []
    assert not _Engine.disposed  # no engine was even built


async def test_a_job_with_no_idempotency_key_is_accepted_because_the_sweep_may_omit_it(
    wired,
) -> None:
    result = await scan.scan_file_task({}, envelope(idempotency_key=""))
    assert result["status"] == "clean"


async def test_a_worker_with_no_database_skips_without_scanning(wired, monkeypatch) -> None:
    monkeypatch.setattr(scan.settings, "database_url", "")
    assert (await scan.scan_file_task({}, envelope()))["status"] == "skipped"
    assert wired["calls"] == []


async def test_the_attempt_threshold_is_the_one_worker_setting_and_defaults_to_twelve(
    wired, monkeypatch
) -> None:
    monkeypatch.delenv("FILE_SCAN_MAX_ATTEMPTS", raising=False)
    await scan.scan_file_task({}, envelope())
    assert wired["calls"][-1]["max_attempts"] == 12

    monkeypatch.setenv("FILE_SCAN_MAX_ATTEMPTS", "7")
    await scan.scan_file_task({}, envelope())
    assert wired["calls"][-1]["max_attempts"] == 7

    monkeypatch.setenv("FILE_SCAN_MAX_ATTEMPTS", "")
    await scan.scan_file_task({}, envelope())
    assert wired["calls"][-1]["max_attempts"] == 12  # a cleared box in the secret store is absent


async def test_the_reader_is_bounded_by_the_configured_ceiling_and_the_scanner_is_the_resolved_one(
    wired, monkeypatch
) -> None:
    monkeypatch.setenv("FILE_SCAN_MAX_BYTES", "1048576")
    monkeypatch.setenv("FILE_SCAN_BACKEND", "none")
    await scan.scan_file_task({}, envelope())
    call = wired["calls"][-1]
    assert call["reader"]._max == 1048576  # noqa: SLF001
    # backend none is the unavailable scanner: it can only hold.
    assert type(call["scanner"]).__name__ == "UnavailableScanner"


def test_the_summary_is_a_closed_vocabulary_and_carries_no_file_content() -> None:
    summary = scan._summary(
        ScanRun(ScanDisposition.HELD, failure=ScanFailure.SCAN_TIMEOUT, attempts=3)
    )
    assert summary == {"status": "held", "failure": "scan_timeout", "attempts": 3}


async def test_the_source_builds_lazily_and_a_missing_store_is_a_hold_not_a_crash(
    monkeypatch,
) -> None:
    for name in ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    source = scan._LazySource()  # constructing it touches nothing
    from koras_worker.scanning import ObjectSourceError

    def broken(_settings: Any) -> Any:
        raise RuntimeError("no bucket configured")

    monkeypatch.setattr(scan, "default_bucket_source", broken)
    with pytest.raises(ObjectSourceError):
        source.stat("tenants/x/y/z/a.csv")


# =========================================================================================
# Started by exactly the finalizer's hand-off and the sweep
# =========================================================================================


def _sources(*roots: str) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        found += [
            p
            for p in (REPO / root).rglob("*.py")
            if "__pycache__" not in p.parts
            and ".venv" not in p.parts
            and "node_modules" not in p.parts
        ]
    return found


def test_only_the_handoff_the_enqueue_helper_and_the_sweep_name_the_task() -> None:
    """The worker that runs the job, the helper that enqueues it, the finalizer's hand-off
    (which is in `tasks/scan.py`) and the sweep. No hook, no route, no admin trigger, no script:
    a fourth importer is a failing test."""
    importers = sorted(
        p.relative_to(REPO).as_posix()
        for p in _sources("services", "python-packages")
        if re.search(r"scan_jobs|\bFILE_SCAN\b", p.read_text(encoding="utf-8"))
        and p.name not in {"scan_jobs.py"}
    )
    assert importers == [
        "services/api/koras_api/core/scan_enqueue.py",
        "services/worker/koras_worker/tasks/scan.py",
        "services/worker/koras_worker/tasks/scan_sweep.py",
    ]


def test_the_task_name_is_spelled_once_outside_documentation() -> None:
    spelled = [
        p.relative_to(REPO).as_posix()
        for p in _sources("services", "python-packages", "apps", "packages")
        if '"file.scan"' in p.read_text(encoding="utf-8")
    ]
    assert spelled == ["services/api/koras_api/core/scan_jobs.py"]


def test_exactly_one_cron_entry_and_one_registration_in_the_worker() -> None:
    worker = (WORKER / "worker.py").read_text(encoding="utf-8")
    assert worker.count("cron(sweep_pending_scans") == 1
    assert worker.count("scan_tasks()") == 1
    assert "file.scan" not in worker, "the name is spelled in the declaration only"


def test_the_api_never_enqueues_a_scan_and_the_finalizer_hands_off_after_the_swap() -> None:
    api = REPO / "services" / "api" / "koras_api"
    for path in api.rglob("*.py"):
        if path.name in {"scan_jobs.py", "scan_enqueue.py", "scan_audit.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "file.scan" not in text and "scan_jobs" not in text, path.name
        assert "enqueue_scan" not in text, path.name
    finalize = (WORKER / "tasks" / "finalize.py").read_text(encoding="utf-8")
    assert "hand_off_to_scanner" in finalize and "on_final=_hand_off(ctx)" in finalize


def test_the_scanner_migrations_follow_the_finalizers_and_the_release_layer_follows_them() -> None:
    names = sorted(p.name for p in (REPO / "supabase" / "migrations").glob("*.sql"))
    assert names[-4:] == [
        "00039_file_scan_attempts.sql",
        "00040_file_scan_interrupted.sql",
        "00041_file_scan_due_indexes.sql",
        "00042_file_derived_content_withdrawal.sql",
    ], names[-4:]


def test_the_persisted_failure_vocabulary_is_the_thirteen_names_of_00040() -> None:
    migration = (REPO / "supabase" / "migrations" / "00040_file_scan_interrupted.sql").read_text(
        encoding="utf-8"
    )
    body = migration.split("check (scan_failure in (")[-1].split("));")[0]
    persisted = set(re.findall(r"'([a-z_]+)'", body))
    assert persisted == {failure.value for failure in ScanFailure}
    assert "scan_interrupted" in persisted and len(persisted) == 13


def test_the_attempt_threshold_is_declared_as_twelve_in_the_worker_configuration() -> None:
    """A typed manifest entry, a code default that agrees, read in one place, no payload."""
    manifest = (REPO / "local" / "config" / "secrets.manifest").read_text(encoding="utf-8")
    assert re.search(r"^FILE_SCAN_MAX_ATTEMPTS optional - int$", manifest, re.M)
    assert ScannerSettings().file_scan_max_attempts == 12
    task_source = (WORKER / "tasks" / "scan.py").read_text(encoding="utf-8")
    assert task_source.count("config.file_scan_max_attempts") == 1, "read in exactly one place"
    api_source = (REPO / "services" / "api" / "koras_api" / "core").rglob("scan_*.py")
    assert not [p for p in api_source if "max_attempts" in p.read_text(encoding="utf-8").lower()]


def test_the_scanner_settings_are_declared_in_the_manifest_with_types() -> None:
    manifest = (REPO / "local" / "config" / "secrets.manifest").read_text(encoding="utf-8")
    for line in (
        "FILE_SCAN_BACKEND supplied - enum:clamd",
        "FILE_SCAN_CLAMD_HOST supplied - nonempty",
        "FILE_SCAN_CLAMD_PORT optional - int",
        "FILE_SCAN_MAX_BYTES optional - int",
        "FILE_SCAN_SWEEP_BATCH_SIZE optional - int",
        "FILE_SCAN_SWEEP_MAX_BATCHES optional - int",
        "FILE_SCAN_SWEEP_NOT_BEFORE optional",
    ):
        assert re.search(rf"^{line}$", manifest, re.M), line
    assert not re.search(r"^FILE_SCAN_SWEEP_ENABLED", manifest, re.M), "there is no switch"
