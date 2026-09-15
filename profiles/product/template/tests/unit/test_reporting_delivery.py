"""Scheduled delivery: the period a cadence names, the next due time, and one
hourly run against a scripted session and a recording sender.

The worker delivers as the tenant, through the product's own catalogue, and
records the run either way. What is proved here is the shape of that: the
tenant is bound before the resolver reads, the file goes to every recipient
as an attachment in the schedule's format, the audit row says so, a
schedule whose report vanished records its error and its next time rather
than stopping the sweep, and the period never includes today.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_api.reporting import catalogue  # noqa: E402
from koras_email import RecordingEmailSender  # noqa: E402
from koras_reporting import DateRange  # noqa: E402
from koras_worker.tasks.reporting import deliver_due, next_run, period_for  # noqa: E402
from reporting_support import ScriptedSession, _Result  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 9, 14, 6, 5, tzinfo=UTC)


class ScheduleSession(ScriptedSession):
    """The scripted session, plus the schedules the sweep asks for."""

    def __init__(self, schedules: list[dict[str, Any]]) -> None:
        super().__init__()
        self._schedules = schedules

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        sql = " ".join(str(statement).split())
        if "from public.report_schedules" in sql:
            self.statements.append((sql, parameters))
            return _Result(self._schedules)
        return await super().execute(statement, parameters)


def test_the_period_is_complete_days_and_never_today() -> None:
    today = date(2026, 9, 14)
    assert period_for("daily", today) == DateRange(date(2026, 9, 13), date(2026, 9, 13))
    weekly = period_for("weekly", today)
    assert (weekly.start, weekly.end) == (date(2026, 9, 7), date(2026, 9, 13))
    monthly = period_for("monthly", today)
    assert (monthly.start, monthly.end) == (date(2026, 8, 1), date(2026, 8, 31))


def test_the_next_run_is_at_the_delivery_hour() -> None:
    assert next_run("daily", NOW) == datetime(2026, 9, 15, 6, tzinfo=UTC)
    # 2026-09-14 is a Monday; the next weekly run is next Monday, not today.
    assert next_run("weekly", NOW) == datetime(2026, 9, 21, 6, tzinfo=UTC)
    assert next_run("monthly", NOW) == datetime(2026, 10, 1, 6, tzinfo=UTC)


async def test_a_due_schedule_is_delivered_as_the_tenant_and_recorded() -> None:
    session = ScheduleSession(
        [
            {
                "id": "s1",
                "tenant_id": TENANT,
                "report_key": "usage.quotas",
                "cadence": "weekly",
                "format": "csv",
                "recipients": ["ada@example.com", "bob@example.com"],
                "filters": {},
            }
        ]
    )
    sender = RecordingEmailSender()
    outcome = await deliver_due(session, catalogue=catalogue, sender=sender, now=NOW)  # type: ignore[arg-type]
    assert outcome == {"due": 1, "delivered": 1, "failed": 0, "paused": 0}

    # Two mails, one attachment each, named for the report and the period.
    assert [m["to"] for m in sender.sent] == ["ada@example.com", "bob@example.com"]
    assert sender.sent[0]["subject"] == "Usage: 2026-09-07 to 2026-09-13"
    assert sender.sent[0]["body"].startswith("Your scheduled report is attached.")
    attachment = sender.attachments[0][0]
    assert attachment.filename == "usage-quotas-2026-09-07-to-2026-09-13.csv"
    assert attachment.content.splitlines()[0] == b"Quota,Used,Included,Remaining,Used %"

    # A German schedule is delivered in German: the same file, other words
    # around it. The report's own name is the definition's and stays.
    german = ScheduleSession(
        [
            {
                "id": "s2",
                "tenant_id": TENANT,
                "report_key": "usage.quotas",
                "cadence": "weekly",
                "format": "csv",
                "recipients": ["ada@example.com"],
                "filters": {},
                "locale": "de",
            }
        ]
    )
    german_sender = RecordingEmailSender()
    await deliver_due(german, catalogue=catalogue, sender=german_sender, now=NOW)  # type: ignore[arg-type]
    assert german_sender.sent[0]["subject"] == "Usage: 2026-09-07 bis 2026-09-13"
    assert german_sender.sent[0]["body"].startswith("Ihr geplanter Bericht ist angehängt.")

    # The tenant was bound before the first read, and every read bound it too.
    sqls = [sql for sql, _ in session.statements]
    bound = next(i for i, sql in enumerate(sqls) if "set_config('app.tenant_id'" in sql)
    first_read = next(
        i
        for i, sql in enumerate(sqls)
        if sql.startswith("select") and "from public." in sql and "report_schedules" not in sql
    )
    assert bound < first_read
    for sql, params in session.statements:
        if sql.startswith("select") and "from public.tenant_members" in sql:
            assert params is not None and params["tenant_id"] == TENANT

    # The audit row, and the run recorded with the next due time.
    audit = session.inserted("audit_events")
    assert audit and audit[0]["action"] == "report.delivered" and audit[0]["tenant_id"] == TENANT
    run = next(p for sql, p in session.statements if "update public.report_schedules" in sql)
    assert run is not None and run["error"] is None
    assert run["next_run_at"] == datetime(2026, 9, 21, 6, tzinfo=UTC)


async def test_a_schedule_whose_report_vanished_records_its_error_and_moves_on() -> None:
    session = ScheduleSession(
        [
            {
                "id": "gone",
                "tenant_id": TENANT,
                "report_key": "nobody.home",
                "cadence": "daily",
                "format": "pdf",
                "recipients": ["ada@example.com"],
                "filters": {},
            },
            {
                "id": "fine",
                "tenant_id": TENANT,
                "report_key": "usage.overview",
                "cadence": "daily",
                "format": "pdf",
                "recipients": ["ada@example.com"],
                "filters": {},
            },
        ]
    )
    sender = RecordingEmailSender()
    outcome = await deliver_due(session, catalogue=catalogue, sender=sender, now=NOW)  # type: ignore[arg-type]
    assert outcome == {"due": 2, "delivered": 1, "failed": 1, "paused": 0}
    runs = [p for sql, p in session.statements if "update public.report_schedules" in sql]
    assert (
        runs[0] is not None and runs[0]["error"] is not None and "LookupError" in runs[0]["error"]
    )
    assert runs[1] is not None and runs[1]["error"] is None
    assert sender.attachments[0][0].content.startswith(b"%PDF")


def _schedule(schedule_id: str, report_key: str) -> dict[str, Any]:
    return {
        "id": schedule_id,
        "tenant_id": TENANT,
        "report_key": report_key,
        "cadence": "daily",
        "format": "csv",
        "recipients": ["ada@example.com"],
        "filters": {},
    }


def _plan(*codes: str) -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "plan_code": "pro",
        "status": "active",
        "entitlements": {code: {"enabled": True, "limit": None} for code in codes},
        "trial_ends_at": None,
        "period_ends_at": None,
        "synced_at": NOW,
    }


async def test_a_plan_that_lapsed_pauses_the_schedule_without_a_mail() -> None:
    # The platform's last word: Pro, which exports but no longer schedules.
    session = ScheduleSession([_schedule("s1", "usage.quotas")])
    session.plans = [_plan("reporting.basic", "reporting.export")]
    sender = RecordingEmailSender()
    outcome = await deliver_due(session, catalogue=catalogue, sender=sender, now=NOW)  # type: ignore[arg-type]
    assert outcome == {"due": 1, "delivered": 0, "failed": 0, "paused": 1}
    assert sender.sent == []
    assert session.inserted("audit_events") == []
    run = next(p for sql, p in session.statements if "update public.report_schedules" in sql)
    assert run is not None and "reporting.scheduled" in str(run["error"])
    assert run["next_run_at"] == datetime(2026, 9, 15, 6, tzinfo=UTC)


async def test_the_report_own_gate_is_asked_again_at_delivery() -> None:
    # Scheduling and exporting are included; the report needs the advanced tier.
    session = ScheduleSession([_schedule("s1", "people.users")])
    session.plans = [_plan("reporting.basic", "reporting.export", "reporting.scheduled")]
    sender = RecordingEmailSender()
    outcome = await deliver_due(session, catalogue=catalogue, sender=sender, now=NOW)  # type: ignore[arg-type]
    assert outcome["paused"] == 1 and sender.sent == []
    run = next(p for sql, p in session.statements if "update public.report_schedules" in sql)
    assert run is not None and "reporting.advanced" in str(run["error"])


async def test_a_synced_plan_that_still_includes_the_report_delivers_with_it() -> None:
    session = ScheduleSession([_schedule("s1", "usage.quotas")])
    session.plans = [_plan("reporting.basic", "reporting.export", "reporting.scheduled")]
    sender = RecordingEmailSender()
    outcome = await deliver_due(session, catalogue=catalogue, sender=sender, now=NOW)  # type: ignore[arg-type]
    assert outcome == {"due": 1, "delivered": 1, "failed": 0, "paused": 0}
    assert len(sender.sent) == 1
    # The snapshot was read as the tenant, after the tenant was bound.
    sqls = [sql for sql, _ in session.statements]
    bound = next(i for i, sql in enumerate(sqls) if "set_config('app.tenant_id'" in sql)
    read = next(i for i, sql in enumerate(sqls) if "from public.tenant_plans" in sql)
    assert bound < read
