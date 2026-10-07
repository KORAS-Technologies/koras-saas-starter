"""The product's own jobs, and whether two of them are ever heavy at once.

GR-352E. An import measured beside a cross-provider backup, in the product's
own image under the 512 MiB it is deployed with, reached the limit. So an
import, a backup's copy, a restore and a scheduled report share one gate, and
this file is where that is asked of the jobs themselves rather than of the
gate or of a constant.

**What is watched is the section, not the lock.** Each job is run through its
real function -- `validate_run`, `back_up_tenant_objects`, `restore_approved`,
`deliver_due` -- over the smallest stores and sessions that let it run, and
each of those marks the moment the job takes hold of a payload and the moment
it lets it go: the read of an import's file, a backup's fetch to its
read-back, a restore's fetch to its write, a report's query to its last mail.
The count is of how many are between those two marks at once.

**The second job starts once the first is inside**, so that whether they
overlap depends on the gate and on nothing about timing: with the gate, the
second waits; without it, the second is inside a moment later.

**Every pair has a second test showing the first can fail**: the same two
jobs with the gate widened, where the count must rise. An assertion that two
things never overlapped proves nothing if they never could have.

A job this product was generated without is skipped, which is right for the
product and would be a hole in the factory's own check: `Generator
Integration` names this file on the row that has all four and fails if any
test in it skipped.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

# The worker builds its `Settings()` at import, and the report catalogue
# builds the API's. This file runs alone as well as in the suite.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_worker import heavy as gate  # noqa: E402
from koras_worker.heavy import IMPORT, heavy  # noqa: E402

TENANT = "00000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 9, 14, 6, 5, tzinfo=UTC)

Job = Callable[[], Awaitable[Any]]


class _Inside:
    """Which jobs hold a payload at this moment, and the most that ever did."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now: list[str] = []
        self.seen: list[str] = []
        self.most = 0
        self.together: set[tuple[str, ...]] = set()

    def enter(self, who: str) -> None:
        with self.lock:
            self.now.append(who)
            self.seen.append(who)
            self.most = max(self.most, len(self.now))
            if len(self.now) > 1:
                self.together.add(tuple(sorted(self.now)))

    def leave(self, who: str) -> None:
        with self.lock:
            self.now.remove(who)

    async def entered(self, who: str) -> None:
        async with asyncio.timeout(5):
            while who not in self.seen:
                await asyncio.sleep(0.005)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:  # noqa: ANN401 - a driver row
        return self._rows[0] if self._rows else None


# ── the four jobs ────────────────────────────────────────────────────────────


def _import(
    monkeypatch: pytest.MonkeyPatch,
    inside: _Inside,
    *,
    read: Callable[[], None] | None = None,
    hold: float = 0.3,
) -> Job:
    """A dry run. Inside from the first row read to the last."""
    task = pytest.importorskip("koras_worker.tasks.imports")
    from koras_import import (
        FieldSpec,
        ImportTarget,
        Operation,
        Validation,
        build_registry,
    )
    from koras_queue import JobEnvelope

    target = ImportTarget(
        key="probe.people",
        label_key="import.target.probe.people",
        permission="imports.manage",
        fields=(FieldSpec(name="name", label_key="import.field.name", required=True),),
        match_keys=("name",),
        operations=(Operation.SKIP_DUPLICATE,),
    )

    def reads() -> None:
        inside.enter("import")
        try:
            time.sleep(hold)
        finally:
            inside.leave("import")

    class Store:
        SourceRefused = LookupError

        async def get(self, _session: object, run_id: str) -> Any:  # noqa: ANN401
            return SimpleNamespace(
                id=run_id,
                status="validating",
                target=target.key,
                operation=Operation.SKIP_DUPLICATE.value,
                format="csv",
                source_file_id="file-1",
                requested_by="user-1",
                committed_by=None,
                job_id=None,
                error=None,
            )

        async def source_bytes(self, *_: object) -> bytes:
            return b"Name\nAda\n"

        def examine(self, *_: object, **__: object) -> Any:  # noqa: ANN401
            (read or reads)()
            verdict = Validation(rows=1, valid=1, errors=())
            return SimpleNamespace(verdict=verdict, template_version=None)

        async def predict_outcome(self, _session: object, *, examined: Any, **_: object) -> Any:  # noqa: ANN401
            return examined.verdict, None

        async def record_validation(self, *_: object, **__: object) -> Any:  # noqa: ANN401
            return SimpleNamespace(value="validated")

        async def fail(self, *_: object) -> None:
            return None

        async def abandon(self, *_: object) -> bool:
            return True

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def execute(self, *_: object, **__: object) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class Engine:
        async def dispose(self) -> None:
            return None

    async def nothing(*_: object, **__: object) -> None:
        return None

    store = Store()
    monkeypatch.setattr(task.imports, "imports_enabled", True)  # activation gate open
    monkeypatch.setattr(task, "settings", SimpleNamespace(database_url="postgresql://x/y"))
    monkeypatch.setattr(task, "_engine", Engine)
    monkeypatch.setattr(task, "async_sessionmaker", lambda *_, **__: Session)
    monkeypatch.setattr(task, "_registry", lambda: build_registry([target]))
    monkeypatch.setattr(task, "_object_store", lambda: object())
    monkeypatch.setattr(task, "_run_store", lambda: store)
    monkeypatch.setattr(task, "_record", nothing)
    numbers = iter(range(1, 100))

    def job() -> Awaitable[Any]:
        envelope = JobEnvelope(
            task="imports.validate", tenant_id=TENANT, payload={"run_id": f"v{next(numbers)}"}
        )
        return task.validate_run({}, envelope)

    return job


def _backup(
    inside: _Inside,
    *,
    size_bytes: int | None = 10,
    fetch: Callable[[], bytes | None] | None = None,
) -> Job:
    """A cross-provider copy of two objects. Inside from the fetch to the read-back."""
    backup = pytest.importorskip("koras_worker.tasks.storage_backup")
    from koras_storage import Destination, Provider

    destination = Destination(
        Provider.SUPABASE, "http://localhost:9000", "backups", "us-east-1", "k", "s"
    )
    due = [
        SimpleNamespace(
            id=f"22222222-2222-2222-2222-22222222222{number}",
            tenant_id=TENANT,
            storage_key=f"tenants/t/documents/f{number}/a.pdf",
            size_bytes=size_bytes,
            checksum_sha256=None,
        )
        for number in (1, 2)
    ]

    class Session:
        async def execute(self, statement: object, _parameters: object = None) -> _Result:
            await asyncio.sleep(0)
            text = str(statement)
            if "from public.files" in text and text.strip().startswith("select"):
                return _Result(list(due))
            return _Result([])

        async def commit(self) -> None:
            return None

    class Source:
        def get(self, _key: str) -> bytes | None:
            inside.enter("backup")
            if fetch is not None:
                return fetch()
            # On the loop, as the job's own fetch is.
            time.sleep(0.02)
            return b"one"

    class Target:
        def put(self, *_: object, **__: object) -> None:
            return None

        def checksum(self, _key: str) -> str | None:
            # Supabase's answer, so the copy is read back.
            return None

        def get(self, _key: str) -> bytes | None:
            inside.leave("backup")
            return b"one"

    def job() -> Awaitable[Any]:
        return backup.back_up_tenant_objects(
            Session(), Source(), Target(), destination, streaming=True, limit=10
        )

    return job


def _restore(
    inside: _Inside,
    *,
    fetch: Callable[[], bytes | None] | None = None,
    statements: list[str] | None = None,
) -> Job:
    """One approved request. Inside from the fetch of the copy to the write of the object."""
    restore = pytest.importorskip("koras_worker.tasks.storage_restore")

    row = SimpleNamespace(
        id="44444444-4444-4444-4444-444444444444",
        tenant_id=TENANT,
        file_id="33333333-3333-3333-3333-333333333333",
        overwrite=False,
        backup_key="tenants/t/documents/f1/a.pdf",
        backup_digest=None,
        size_bytes=10,
    )

    class Session:
        async def execute(self, statement: object, _parameters: object = None) -> _Result:
            text = " ".join(str(statement).split())
            if statements is not None:
                statements.append(text)
            if "from public.restore_requests" in text:
                return _Result([row])
            if "set status = 'restoring'" in text:
                return _Result([row])
            if "from public.files" in text or "app.tenant_id" in text:
                # While the copy is in hand: the job is waiting on its
                # database, and every other job has the loop.
                await asyncio.sleep(0.1)
            return _Result([])

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class Source:
        def get(self, _key: str) -> bytes | None:
            inside.enter("restore")
            return fetch() if fetch is not None else b"the original bytes"

    class Target:
        def put(self, *_: object, **__: object) -> None:
            inside.leave("restore")

    def job() -> Awaitable[Any]:
        return restore.restore_approved(Session(), Source(), Target())

    return job


def _report(
    inside: _Inside,
    fmt: str,
    *,
    answer: Callable[[], None] | None = None,
) -> Job:
    """One due schedule. Inside from the query that answers it to the mail that carries it."""
    reporting = pytest.importorskip("koras_worker.tasks.reporting")
    from koras_email import RecordingEmailSender
    from koras_reporting import (
        Category,
        ReportDefinition,
        ReportResult,
        Table,
        TableColumn,
        build_catalogue,
    )
    from reporting_support import ScriptedSession
    from reporting_support import _Result as Scripted

    async def resolver(_context: object, _filters: object) -> ReportResult:
        inside.enter("report")
        if answer is not None:
            answer()
        await asyncio.sleep(0.2)
        return ReportResult(
            key="probe.rows",
            generated_at=NOW,
            table=Table(
                columns=[TableColumn(key="n", label="N")],
                rows=[{"n": number} for number in range(3)],
            ),
        )

    catalogue = build_catalogue(
        [],
        [
            ReportDefinition(
                key="probe.rows",
                name="Probe",
                description="Three rows.",
                category=Category.PRODUCT,
                resolver=resolver,
                permission="reports.view",
            )
        ],
    )
    schedule = {
        "id": "s1",
        "tenant_id": TENANT,
        "report_key": "probe.rows",
        "cadence": "daily",
        "format": fmt,
        "recipients": ["ada@example.com"],
        "filters": {},
    }

    class Session(ScriptedSession):
        async def execute(self, statement: object, parameters: Any = None) -> Any:  # noqa: ANN401
            sql = " ".join(str(statement).split())
            if "from public.report_schedules" in sql:
                return Scripted([schedule])
            return await super().execute(statement, parameters)

    class Sender(RecordingEmailSender):
        async def send(self, **message: Any) -> Any:  # noqa: ANN401
            sent = await super().send(**message)
            inside.leave("report")
            return sent

    def job() -> Awaitable[Any]:
        return reporting.deliver_due(Session(), catalogue=catalogue, sender=Sender(), now=NOW)

    return job


def _jobs(monkeypatch: pytest.MonkeyPatch, inside: _Inside, first: str, second: str) -> list[Job]:
    """Two jobs, the first of which is one that waits on something while it is inside."""

    def one(name: str) -> Job:
        if name == "import":
            return _import(monkeypatch, inside)
        if name == "backup":
            return _backup(inside)
        if name == "restore":
            return _restore(inside)
        return _report(inside, name)

    if first == second:
        job = one(first)
        return [job, job]
    return [one(first), one(second)]


def _label(name: str) -> str:
    return "report" if name in ("xlsx", "pdf") else name


#: The first of each pair is inside when the second asks. A backup is never
#: first: its copy has no `await` in it, so nothing can arrive in the middle
#: of one -- which is a fact about the job, and not what keeps it apart from
#: a restore or a report that is waiting on its database with an object in
#: hand.
PAIRS = [
    ("import", "import"),
    ("import", "backup"),
    ("import", "restore"),
    ("import", "xlsx"),
    ("import", "pdf"),
    ("restore", "backup"),
    ("xlsx", "backup"),
    ("pdf", "backup"),
]


async def _both(inside: _Inside, jobs: list[Job], first: str) -> list[Any]:
    async def after_the_first_is_inside() -> Any:  # noqa: ANN401
        await inside.entered(_label(first))
        return await jobs[1]()

    async with asyncio.timeout(20):
        return await asyncio.gather(jobs[0](), after_the_first_is_inside())


@pytest.mark.parametrize(("first", "second"), PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
async def test_two_heavy_jobs_never_hold_a_payload_at_once(
    monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    assert gate.HEAVY_SLOTS == 1
    inside = _Inside()

    await _both(inside, _jobs(monkeypatch, inside, first, second), first)

    # Both ran: nobody was refused for waiting.
    assert {_label(first), _label(second)} <= set(inside.seen)
    assert len(inside.seen) >= 2
    assert inside.most == 1, f"held at once: {sorted(inside.together)}"
    assert gate.occupancy() == {}


@pytest.mark.parametrize(("first", "second"), PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
async def test_the_same_two_do_overlap_when_the_gate_is_widened(
    monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    monkeypatch.setattr(gate, "HEAVY_SLOTS", 4)
    if first == second == "import":
        task = pytest.importorskip("koras_worker.tasks.imports")

        monkeypatch.setattr(task, "IMPORT_SLOTS", 4)
    inside = _Inside()

    await _both(inside, _jobs(monkeypatch, inside, first, second), first)

    assert tuple(sorted((_label(first), _label(second)))) in inside.together


async def test_two_imports_stay_apart_if_only_the_gate_is_widened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`IMPORT_SLOTS` is still a limit of its own, inside the gate."""
    monkeypatch.setattr(gate, "HEAVY_SLOTS", 4)
    inside = _Inside()

    await _both(inside, _jobs(monkeypatch, inside, "import", "import"), "import")

    assert inside.seen == ["import", "import"] and inside.most == 1


# ── what does not wait ───────────────────────────────────────────────────────


async def test_a_job_that_holds_no_payload_is_not_held_up_by_an_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ten job slots, still. The gate is not `max_jobs = 1`."""
    from koras_worker.tasks import example_task

    release = threading.Event()
    inside = _Inside()

    def read() -> None:
        inside.enter("import")
        release.wait(5)
        inside.leave("import")

    importing = asyncio.ensure_future(_import(monkeypatch, inside, read=read)())
    await inside.entered("import")
    assert gate.occupancy() == {IMPORT: 1}

    async with asyncio.timeout(2):
        answers = await asyncio.gather(*(example_task({}, {"n": n}) for n in range(10)))

    assert [answer["status"] for answer in answers] == ["ok"] * 10
    assert not importing.done(), "the import ended before the light jobs did"
    release.set()
    await importing


async def test_the_parts_of_a_backup_that_hold_nothing_do_not_wait_for_the_gate() -> None:
    """An object past the stream ceiling is skipped unread, and the bookkeeping is rows.

    Neither is held behind an import: only a copy that can put an object's
    bytes in this process asks for the gate.
    """
    backup = pytest.importorskip("koras_worker.tasks.storage_backup")
    inside = _Inside()

    async with heavy(IMPORT):
        async with asyncio.timeout(2):
            summary = await _backup(inside, size_bytes=backup.STREAM_CEILING + 1)()

    assert summary.skipped == 2 and summary.partial
    assert inside.seen == [], "an object too large to read was read"


async def test_a_copy_that_can_hold_an_object_does_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test above can fail: the same run with objects that are read waits."""
    pytest.importorskip("koras_worker.tasks.storage_backup")
    inside = _Inside()

    async with heavy(IMPORT):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.3):
                await _backup(inside)()

    assert inside.seen == []


async def test_a_restore_that_is_waiting_has_not_claimed_its_request() -> None:
    """The queue cancels a sweep that waits too long, and the request must survive that.

    Claimed and then cancelled would be `restoring` for ever: the sweep picks
    up `approved` and nothing else.
    """
    pytest.importorskip("koras_worker.tasks.storage_restore")
    inside = _Inside()
    statements: list[str] = []

    async with heavy(IMPORT):
        waiting = asyncio.ensure_future(_restore(inside, statements=statements)())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    assert not [text for text in statements if "set status = 'restoring'" in text]
    assert inside.seen == []
    assert gate.occupancy() == {}


# ── every way out lets go ────────────────────────────────────────────────────


def _breaks() -> None:
    raise RuntimeError("the provider went away")


@pytest.mark.parametrize("name", ["import", "backup", "restore", "xlsx", "pdf"])
async def test_a_job_that_fails_inside_its_section_lets_the_next_one_in(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    inside = _Inside()
    if name == "import":
        failing = _import(monkeypatch, inside, read=_breaks)
    elif name == "backup":
        failing = _backup(inside, fetch=_breaks)
    elif name == "restore":
        failing = _restore(inside, fetch=_breaks)
    else:
        failing = _report(inside, name, answer=_breaks)

    # Each of these records its failure and returns: none of them raises.
    await failing()

    assert gate.occupancy() == {}
    async with asyncio.timeout(2):
        async with heavy(IMPORT):
            pass


@pytest.mark.parametrize("name", ["import", "restore", "xlsx", "pdf"])
async def test_a_job_cancelled_inside_its_section_lets_the_next_one_in(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The queue's timeout, or a deploy. A backup's copy has no `await` to be cancelled at."""
    inside = _Inside()
    stop = threading.Event()

    def read() -> None:
        inside.enter("import")
        stop.wait(5)
        inside.leave("import")

    if name == "import":
        task = pytest.importorskip("koras_worker.tasks.imports")

        # The read is told to stop through its budget; this one is told here.
        monkeypatch.setattr(task, "_STOP_GRACE_SECONDS", 0.05)
        job = _import(monkeypatch, inside, read=read)
    elif name == "restore":
        job = _restore(inside)
    else:
        job = _report(inside, name)

    running = asyncio.ensure_future(job())
    await inside.entered(_label(name))
    assert gate.occupancy() != {}
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    stop.set()

    assert gate.occupancy() == {}
    async with asyncio.timeout(2):
        async with heavy(IMPORT):
            pass
