"""Reporting's two sweeps: the audit table's retention, and scheduled delivery.

The retention sweep is the AI one's shape exactly: on the provisioning
context, which migration 00013 admits for this delete and nothing else,
with the pure statement taking the session so a test needs no database.
`AUDIT_RETENTION_DAYS` is its own setting, read here rather than by every
worker, and a year unless set.

Delivery runs hourly. On the provisioning context it reads every schedule
that is due; for each it opens a transaction as that tenant -- the same
`app.tenant_id` setting the API binds, set for the transaction and nothing
longer -- resolves the report through the product's own catalogue for the
period the cadence names, renders it in the schedule's format, mails it to
each recipient as an attachment, records `report.delivered` in the
tenant's audit table, and then, back on the provisioning context, records
the run and the next due time on the schedule. A schedule that fails keeps
its error and its next time, so one bad night does not stop the report
for good and does not repeat it every hour either.

The plan is the one the platform last synced into `tenant_plans`: the
worker holds no customer token to resolve it live, and the product holds
no identity toward the platform to ask, so the platform tells it hourly
through the private contract. A schedule whose plan no longer includes
scheduling, exporting or the report is paused -- its error says so and
its next time is set -- rather than delivered on a plan that lapsed.

The catalogue is the API's, imported by name. The worker image carries the
API's `reporting` package on its path for exactly this; nothing else of the
API is imported, and the modules under it import only the framework and
SQLAlchemy.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from koras_email import Attachment, EmailSender, sender_for
from koras_reporting import (
    UNRESOLVED_PLAN,
    DateRange,
    Entitlement,
    ExportFormat,
    Plan,
    ReportContext,
    ReportDefinition,
    ReportingCatalogue,
    ResolvedFilters,
    Scope,
    export_filename,
    render,
    resolve_filters,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import settings


class ReportingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Days an audit row is kept. A year: long enough to answer a question
    #: about last quarter, short enough to stop growing forever.
    audit_retention_days: int = 365

    #: The same SMTP settings the API's approval notices use. Unset means
    #: deliveries are recorded and logged rather than sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from: str = ""
    smtp_secure: bool = True
    smtp_username: str = ""
    smtp_password: str = ""


reporting = ReportingSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
_PURGE_AUDIT = text("delete from public.audit_events where created_at < :before returning id")

_DUE = text(
    "select id::text as id, tenant_id::text as tenant_id, report_key, cadence, format, "
    " recipients, filters "
    "from public.report_schedules "
    "where active and next_run_at <= :now "
    "order by next_run_at limit :limit"
)

_RECORD_RUN = text(
    "update public.report_schedules "
    "set last_run_at = :now, next_run_at = :next_run_at, last_error = :error "
    "where id = :id"
)

_PLAN = text(
    "select plan_code, status, entitlements, trial_ends_at, period_ends_at, synced_at "
    "from public.tenant_plans where tenant_id = :tenant_id"
)

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details) "
    "values (:tenant_id, 'system', :action, 'report', :target_id, :outcome, "
    " cast(:details as jsonb))"
)

#: How many schedules one hourly run delivers at most.
BATCH = 200
DELIVERY_HOUR = 6


# ── the pure parts ────────────────────────────────────────────────────────────


def period_for(cadence: str, today: date) -> DateRange:
    """The period a cadence reports on: yesterday, the last seven days, or the
    previous calendar month -- always complete days, never today."""
    yesterday = today - timedelta(days=1)
    if cadence == "daily":
        return DateRange(yesterday, yesterday)
    if cadence == "weekly":
        return DateRange(yesterday - timedelta(days=6), yesterday)
    first_of_this = today.replace(day=1)
    last_of_previous = first_of_this - timedelta(days=1)
    return DateRange(last_of_previous.replace(day=1), last_of_previous)


def next_run(cadence: str, now: datetime) -> datetime:
    """The next delivery after `now`, at the delivery hour, UTC."""
    at = now.astimezone(UTC).replace(hour=DELIVERY_HOUR, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        return at + timedelta(days=1)
    if cadence == "weekly":
        return at + timedelta(days=(7 - at.weekday()) % 7 or 7)
    return (at.replace(day=1) + timedelta(days=32)).replace(day=1)


def mail_sender() -> EmailSender:
    return sender_for(
        host=reporting.smtp_host,
        port=reporting.smtp_port,
        username=reporting.smtp_username or None,
        password=reporting.smtp_password or None,
        sender=reporting.smtp_from,
        use_tls=reporting.smtp_secure,
    )


class Catalogue(Protocol):
    reports: Any


class PlanLapsed(Exception):
    """The plan the platform last told us of no longer includes this delivery."""


#: What a delivery needs the plan to include, beside the report's own gate.
SCHEDULED = "reporting.scheduled"
EXPORT = "reporting.export"


def plan_from_row(row: Row[Any]) -> Plan:
    """The stored snapshot as the plan a resolver reads."""
    raw = row.entitlements
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    rows: dict[str, Entitlement] = {}
    for code, value in (raw or {}).items():
        if not isinstance(value, dict):
            continue
        limit = value.get("limit")
        rows[str(code)] = Entitlement(
            enabled=bool(value.get("enabled")),
            limit=int(limit) if isinstance(limit, int) and limit >= 0 else None,
        )
    return Plan(
        resolved=True,
        code=row.plan_code,
        status=row.status,
        trial_ends_at=row.trial_ends_at,
        period_ends_at=row.period_ends_at,
        entitlements=rows,
    )


async def tenant_plan(session: AsyncSession, tenant_id: str) -> Plan:
    """The plan the platform last synced for this tenant, or the unresolved default.

    Unresolved when the platform has never told this product about the
    tenant -- a product deployed before the sync, or a platform that has not
    run it yet. The basic reports still deliver then, as they answer a
    signed-in customer whose plan could not be read.
    """
    row = (await session.execute(_PLAN, {"tenant_id": tenant_id})).first()
    return UNRESOLVED_PLAN if row is None else plan_from_row(row)


def refuse_if_lapsed(plan: Plan, definition: ReportDefinition) -> None:
    """A resolved plan must still include scheduling, exporting and the report.

    The same three gates creating the schedule took, asked again with what
    the platform said last. Unresolved is not lapsed: nothing is known, and
    the report answers as it does for an unresolved customer.
    """
    if not plan.resolved:
        return
    for code in (SCHEDULED, EXPORT, definition.entitlement):
        if code is not None and not plan.includes(code):
            raise PlanLapsed(
                f"the plan no longer includes {code}; delivery is paused until it does"
            )


def load_catalogue() -> ReportingCatalogue | None:
    """The product's catalogue, by name; None where the worker cannot see it.

    By name and not by an import statement on purpose: the worker does not
    depend on the API's distribution and must not, so the dependency check
    would rightly refuse a plain import. What the image carries is the
    `koras_api/reporting` package alone, put on the path by the Dockerfile,
    and this is the one place the worker reads it.
    """
    try:
        module = importlib.import_module("koras_api.reporting")
    except ImportError:
        logger.error("scheduled reports: the product's catalogue is not on this worker's path")
        return None
    catalogue = getattr(module, "catalogue", None)
    if not isinstance(catalogue, ReportingCatalogue):
        logger.error("scheduled reports: koras_api.reporting has no catalogue")
        return None
    return catalogue


async def deliver_one(
    session: AsyncSession,
    schedule: dict[str, Any],
    *,
    definition: ReportDefinition,
    sender: EmailSender,
    today: date,
    now: datetime,
) -> int:
    """Render one schedule's report as its tenant and mail it. Returns recipients sent to."""
    tenant_id = str(schedule["tenant_id"])
    await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
    plan = await tenant_plan(session, tenant_id)
    refuse_if_lapsed(plan, definition)
    period = period_for(str(schedule["cadence"]), today)
    raw_filters = schedule.get("filters") or {}
    if not isinstance(raw_filters, dict):
        raw_filters = {}
    resolved = resolve_filters(definition, {k: str(v) for k, v in raw_filters.items()})
    filters = ResolvedFilters(range=period, values=resolved.values)
    context = ReportContext(
        scope=Scope.TENANT,
        user_id="system",
        permissions=frozenset({definition.permission}),
        plan=plan,
        session=session,
        tenant_id=tenant_id,
        now=now,
    )
    result = await definition.resolver(context, filters)
    fmt = ExportFormat(str(schedule["format"]))
    rendered = render(result, fmt, title=definition.name)
    filename = export_filename(
        definition.key, period.start.isoformat(), period.end.isoformat(), fmt.value
    )
    recipients: Sequence[str] = list(schedule.get("recipients") or [])
    subject = f"{definition.name}: {period.start.isoformat()} to {period.end.isoformat()}"
    body = (
        f"Your scheduled report is attached.\n\n"
        f"{definition.name}, {period.start.isoformat()} to {period.end.isoformat()}, "
        f"as {fmt.value.upper()}.\n"
    )
    sent = 0
    for to in recipients:
        await sender.send(
            to=to,
            subject=subject,
            body=body,
            tag="report-delivery",
            attachments=[Attachment(filename, rendered.content, rendered.media_type.split(";")[0])],
        )
        sent += 1
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": tenant_id,
            "action": "report.delivered",
            "target_id": definition.key,
            "outcome": "ok",
            "details": _json(
                {
                    "schedule_id": str(schedule["id"]),
                    "recipients": sent,
                    "format": fmt.value,
                    "from": period.start.isoformat(),
                    "to": period.end.isoformat(),
                    "simulated": sender.simulated,
                }
            ),
        },
    )
    await session.commit()
    return sent


async def deliver_due(
    session: AsyncSession,
    *,
    catalogue: ReportingCatalogue,
    sender: EmailSender,
    now: datetime | None = None,
) -> dict[str, int]:
    """Every schedule that is due, one transaction each, the run recorded either way."""
    now = now or datetime.now(UTC)
    today = now.date()
    await session.execute(_PROVISIONING)
    due = [
        dict(row) for row in (await session.execute(_DUE, {"now": now, "limit": BATCH})).mappings()
    ]
    await session.commit()
    delivered = failed = paused = 0
    for schedule in due:
        definition = catalogue.reports.get(str(schedule["report_key"]))
        error: str | None = None
        try:
            if definition is None:
                raise LookupError(f"report {schedule['report_key']} is no longer registered")
            await deliver_one(
                session, schedule, definition=definition, sender=sender, today=today, now=now
            )
            delivered += 1
        except PlanLapsed as lapsed:
            # Not a failure: nothing broke, the customer's plan changed. The
            # reason is the customer's to read on the schedule, and the next
            # time is set, so the report resumes by itself if the plan does.
            await session.rollback()
            paused += 1
            error = str(lapsed)
            logger.info("scheduled report %s paused: %s", schedule["id"], lapsed)
        except Exception as problem:
            await session.rollback()
            failed += 1
            error = (
                f"{type(problem).__name__}: the delivery failed; the reason is in the server log"
            )
            logger.exception("scheduled report %s failed", schedule["id"])
        await session.execute(_PROVISIONING)
        await session.execute(
            _RECORD_RUN,
            {
                "id": schedule["id"],
                "now": now,
                "next_run_at": next_run(str(schedule["cadence"]), now),
                "error": error,
            },
        )
        await session.commit()
    return {"due": len(due), "delivered": delivered, "failed": failed, "paused": paused}


def _json(values: dict[str, Any]) -> str:
    return json.dumps(values, sort_keys=True)


# ── the retention sweep ───────────────────────────────────────────────────────


async def purge_audit_events(session: AsyncSession, *, retention_days: int) -> int:
    """Remove audit rows older than `retention_days`; return how many."""
    if retention_days < 1:
        raise ValueError("AUDIT_RETENTION_DAYS must be at least 1; retention of nothing is a wipe")
    before = datetime.now(UTC) - timedelta(days=retention_days)
    await session.execute(_PROVISIONING)
    removed = len((await session.execute(_PURGE_AUDIT, {"before": before})).all())
    await session.commit()
    return removed


# ── the tasks ─────────────────────────────────────────────────────────────────


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def purge_audit_history(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly sweep. Skips, loudly, when the worker has no database."""
    if not settings.database_url:
        logger.warning("audit retention skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_audit_events(
                session, retention_days=reporting.audit_retention_days
            )
    finally:
        await engine.dispose()
    logger.info(
        "audit retention removed %d row(s) older than %d days",
        removed,
        reporting.audit_retention_days,
    )
    return {"status": "ok", "removed": removed, "retention_days": reporting.audit_retention_days}


async def deliver_scheduled_reports(ctx: dict[str, Any]) -> dict[str, Any]:
    """The hourly delivery. Skips, loudly, when the worker has no database or no catalogue."""
    if not settings.database_url:
        logger.warning("scheduled reports skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    catalogue = load_catalogue()
    if catalogue is None:
        return {"status": "skipped", "reason": "no catalogue"}
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            outcome = await deliver_due(session, catalogue=catalogue, sender=mail_sender())
    finally:
        await engine.dispose()
    logger.info("scheduled reports: %s", outcome)
    return {"status": "ok", **outcome}
