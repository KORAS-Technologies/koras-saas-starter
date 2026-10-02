"""A scheduled delivery carries as many rows as an export does, and no more.

GR-352E. The export route has always had a bound: past `EXPORT_ROW_LIMIT` a
download stops being the response and becomes a file in the tenant's bucket.
The worker's delivery never read it. A schedule over a report that had grown
was resolved, rendered as a workbook or a PDF whole in the worker's memory,
and attached to a mail for every recipient -- with no ceiling on any of it,
beside whatever else the worker held.

It reads the same number now, and because a delivery has no bucket to fall
back to, past it the delivery is refused. What is asserted here:

- exactly at the bound a workbook, a PDF and a CSV are delivered as they were;
- one row past it, nothing is rendered and nobody is sent anything -- not the
  first recipient of three either;
- the refusal is on the schedule in words its owner can act on, with the next
  time set so that it is not retried every hour;
- the worker's heavy gate is let go by the refusal;
- and the bound is the framework's own number, not a second one.

The rows are made here, in memory, at the real size. A boundary asserted
against a smaller number that was patched in would prove the comparison and
not that ten thousand rows of each format are in fact deliverable.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
import koras_reporting  # noqa: E402
import koras_worker.tasks.reporting as task  # noqa: E402
from koras_email import RecordingEmailSender  # noqa: E402
from koras_reporting import (  # noqa: E402
    Category,
    ReportDefinition,
    ReportingCatalogue,
    ReportResult,
    Table,
    TableColumn,
    build_catalogue,
)
from koras_worker import heavy as gate  # noqa: E402
from reporting_support import ScriptedSession, _Result  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 9, 14, 6, 5, tzinfo=UTC)
BOUND = 10_000
RECIPIENTS = ["ada@example.com", "bob@example.com", "cy@example.com"]


def _catalogue(rows: int) -> ReportingCatalogue:
    """One report, answering a table of exactly `rows` rows."""

    async def resolver(_context: object, _filters: object) -> ReportResult:
        return ReportResult(
            key="probe.rows",
            generated_at=NOW,
            table=Table(
                columns=[TableColumn(key="n", label="N"), TableColumn(key="name", label="Name")],
                rows=[{"n": number, "name": f"row {number}"} for number in range(rows)],
            ),
        )

    return build_catalogue(
        [],
        [
            ReportDefinition(
                key="probe.rows",
                name="Probe",
                description="As many rows as the test asks for.",
                category=Category.PRODUCT,
                resolver=resolver,
                permission="reports.view",
            )
        ],
    )


class _Session(ScriptedSession):
    def __init__(self, fmt: str) -> None:
        super().__init__()
        self._schedule = {
            "id": "s1",
            "tenant_id": TENANT,
            "report_key": "probe.rows",
            "cadence": "daily",
            "format": fmt,
            "recipients": list(RECIPIENTS),
            "filters": {},
        }

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        sql = " ".join(str(statement).split())
        if "from public.report_schedules" in sql:
            self.statements.append((sql, parameters))
            return _Result([self._schedule])
        return await super().execute(statement, parameters)

    def recorded_run(self) -> dict[str, Any]:
        run = next(p for sql, p in self.statements if "update public.report_schedules" in sql)
        assert run is not None
        return run


@pytest.fixture
def rendered(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every file the task made, by format. The real writer still makes it."""
    made: list[str] = []
    real = task.render

    def render(result: Any, fmt: Any, **options: Any) -> Any:  # noqa: ANN401
        made.append(str(fmt.value))
        return real(result, fmt, **options)

    monkeypatch.setattr(task, "render", render)
    return made


def test_the_bound_is_derived_from_the_framework_s_number_and_is_not_a_second_one() -> None:
    assert task.SCHEDULED_DELIVERY_ROW_LIMIT is koras_reporting.EXPORT_ROW_LIMIT
    assert task.SCHEDULED_DELIVERY_ROW_LIMIT == BOUND


@pytest.mark.parametrize(
    ("fmt", "opens_with"), [("xlsx", b"PK"), ("pdf", b"%PDF"), ("csv", b"N,Name")]
)
async def test_a_report_of_exactly_the_bound_is_delivered(
    rendered: list[str], fmt: str, opens_with: bytes
) -> None:
    session = _Session(fmt)
    sender = RecordingEmailSender()

    outcome = await task.deliver_due(session, catalogue=_catalogue(BOUND), sender=sender, now=NOW)  # type: ignore[arg-type]

    assert outcome == {"due": 1, "delivered": 1, "failed": 0, "paused": 0}
    assert rendered == [fmt]
    assert [mail["to"] for mail in sender.sent] == RECIPIENTS
    for attachments in sender.attachments:
        assert attachments[0].content.startswith(opens_with)
    assert session.recorded_run()["error"] is None
    audit = session.inserted("audit_events")
    assert audit and audit[0]["action"] == "report.delivered"


@pytest.mark.parametrize("fmt", ["xlsx", "pdf", "csv"])
async def test_one_row_past_the_bound_is_refused_before_anything_is_made_or_sent(
    rendered: list[str], fmt: str
) -> None:
    session = _Session(fmt)
    sender = RecordingEmailSender()

    outcome = await task.deliver_due(
        session,  # type: ignore[arg-type]
        catalogue=_catalogue(BOUND + 1),
        sender=sender,
        now=NOW,
    )

    assert outcome == {"due": 1, "delivered": 0, "failed": 1, "paused": 0}
    # No file, and nobody written to -- not the first of the three either.
    assert rendered == []
    assert sender.sent == [] and sender.attachments == []
    # Nothing says it was delivered.
    assert session.inserted("audit_events") == []
    # The schedule says why, in words its owner can act on, and when it is
    # asked again.
    run = session.recorded_run()
    assert "10001 rows" in run["error"] and "at most 10000" in run["error"]
    assert "narrow its filters" in run["error"]
    assert run["next_run_at"] == datetime(2026, 9, 15, 6, tzinfo=UTC)
    # And the gate was let go by the refusal.
    assert gate.occupancy() == {}


async def test_the_refusal_above_is_the_bound_s_doing(
    monkeypatch: pytest.MonkeyPatch, rendered: list[str]
) -> None:
    """What this path did before: with the bound out of reach, the same report goes out."""
    monkeypatch.setattr(task, "SCHEDULED_DELIVERY_ROW_LIMIT", 10**9)
    session = _Session("xlsx")
    sender = RecordingEmailSender()

    outcome = await task.deliver_due(
        session,  # type: ignore[arg-type]
        catalogue=_catalogue(BOUND + 1),
        sender=sender,
        now=NOW,
    )

    assert outcome["delivered"] == 1 and rendered == ["xlsx"]
    assert len(sender.sent) == len(RECIPIENTS)


async def test_the_rows_are_counted_inside_the_gate_and_the_file_is_never_begun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal is raised with the gate held, and before `render` is reached.

    The rows are in hand when they are counted -- a resolver answers whole --
    so the count has to happen where a payload may be held.
    """
    seen: list[dict[str, int]] = []
    real = task.row_count

    def row_count(result: Any) -> int:  # noqa: ANN401
        seen.append(gate.occupancy())
        return real(result)

    def render(*_: object, **__: object) -> None:
        pytest.fail("a report past the bound was rendered")

    monkeypatch.setattr(task, "row_count", row_count)
    monkeypatch.setattr(task, "render", render)

    await task.deliver_due(
        _Session("pdf"),  # type: ignore[arg-type]
        catalogue=_catalogue(BOUND + 1),
        sender=RecordingEmailSender(),
        now=NOW,
    )

    assert seen == [{gate.REPORT: 1}]
