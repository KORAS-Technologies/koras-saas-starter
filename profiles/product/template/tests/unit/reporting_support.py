"""A session that answers the standard reports' statements from a script.

Routed by what the statement reads, so the resolvers run their real SQL
text against it and a test can assert what they bound. Nothing here parses
SQL: a handful of substrings tell the tables and shapes apart, and an
unknown statement answers an empty result rather than raising, which is
what a table with no rows would do.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

BUCKET = datetime(2026, 9, 1, tzinfo=UTC)


class Row(dict[str, Any]):
    """A row a router reads by attribute and a resolver by mapping."""

    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


class _Result:
    def __init__(self, rows: list[dict[str, Any]], scalar: object = None) -> None:
        self._rows = [Row(r) for r in rows]
        self._scalar = scalar

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Iterator[Row]:
        return iter(self._rows)

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchall(self) -> list[Row]:
        return list(self._rows)

    def first(self) -> Row | None:
        return self._rows[0] if self._rows else None


class ScriptedSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.commits = 0
        self.rollbacks = 0
        #: Schedules the session holds, as the rows the routes select.
        self.schedules: list[dict[str, Any]] = []
        #: Background exports the session answers with, for the exports routes.
        self.exports: list[dict[str, Any]] = []
        #: The plan snapshot rows the session answers with; none means unresolved.
        self.plans: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.statements.clear()

    def inserted(self, table: str) -> list[dict[str, Any]]:
        return [
            params or {}
            for sql, params in self.statements
            if sql.startswith("insert into public." + table)
        ]

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        sql = " ".join(str(statement).split())
        self.statements.append((sql, parameters))
        return _Result(*self._answer(sql, parameters or {}))

    def _schedules_answer(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if sql.startswith("insert"):
            row = {
                "id": f"schedule-{len(self.schedules) + 1}",
                "report_key": params["report_key"],
                "cadence": params["cadence"],
                "format": params["format"],
                "recipients": list(params["recipients"]),
                "filters": json.loads(params["filters"]),
                "locale": params.get("locale", "en"),
                "active": True,
                "next_run_at": params["next_run_at"],
                "last_run_at": None,
                "last_error": None,
                "created_by": params["created_by"],
                "created_at": BUCKET,
            }
            self.schedules.append(row)
            return [row]
        if sql.startswith("delete"):
            kept = [s for s in self.schedules if s["id"] != params["id"]]
            gone = [s for s in self.schedules if s["id"] == params["id"]]
            self.schedules = kept
            return [{"report_key": s["report_key"]} for s in gone]
        if sql.startswith("update"):
            return []
        wanted = params.get("report_key")
        return [s for s in self.schedules if wanted is None or s["report_key"] == wanted]

    def _answer(self, sql: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], object]:
        if "public.report_schedules" in sql:
            return self._schedules_answer(sql, params), None
        if "public.tenant_plans" in sql:
            wanted = params.get("tenant_id")
            return [p for p in self.plans if p.get("tenant_id") in (None, wanted)], None
        if "public.report_exports" in sql:
            if sql.startswith("select id::text as id, storage_key from"):
                return [], None  # nothing past the retention
            if sql.startswith("select"):
                wanted = params.get("id")
                return [e for e in self.exports if wanted is None or e["id"] == wanted], None
            return [], None
        if sql.startswith("insert") or sql.startswith("select set_config"):
            return [], None
        if "public.tenant_members" in sql:
            if "group by role" in sql:
                return [
                    {"role": "member", "value": 3},
                    {"role": "organization_owner", "value": 1},
                ], None
            if "date_trunc" in sql:
                return [{"bucket": BUCKET, "value": 1}], None
            if ":start" in sql:
                return [], 1
            return [], 4
        if "public.files" in sql:
            if "date_trunc" in sql:
                return [{"bucket": BUCKET, "value": 2}], None
            if ":start" in sql:
                return [], 2
            return [{"files": 5, "bytes": 1024 * 1024}], None
        if "public.audit_events" in sql:
            if "date_trunc" in sql:
                return [{"bucket": BUCKET, "value": 7}], None
            if "group by action" in sql:
                return [
                    {"action": "report.exported", "outcome": "ok", "value": 5},
                    {"action": "report.viewed", "outcome": "denied", "value": 2},
                ], None
            if "order by created_at desc" in sql:
                return [
                    {
                        "actor_id": "user-1",
                        "action": "report.exported",
                        "target_type": "report",
                        "target_id": "usage.quotas",
                        "outcome": "ok",
                        "created_at": BUCKET,
                    },
                    {
                        "actor_id": "user-2",
                        "action": "report.viewed",
                        "target_type": "report",
                        "target_id": "people.users",
                        "outcome": "denied",
                        "created_at": BUCKET,
                    },
                ], None
            return [{"events": 7, "actors": 2}], None
        if "public.ai_usage_events" in sql:
            if "date_trunc" in sql:
                return [{"bucket": BUCKET, "calls": 3, "tokens": 390}], None
            if "group by 1, 2, 3" in sql:
                return [
                    {
                        "model_alias": "koras-balanced",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "calls": 3,
                        "errors": 1,
                        "tokens": 390,
                        "cost": 99,
                        "latency": 812,
                    }
                ], None
            if "date_trunc('month'" in sql:
                return [], 3
            return [
                {
                    "calls": 3,
                    "errors": 1,
                    "tokens": 390,
                    "cost": 99,
                    "billable": 0,
                    "latency": 812,
                    "unpriced": 1,
                }
            ], None
        return [], 0
