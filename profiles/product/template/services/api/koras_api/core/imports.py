"""Where an import run lives, and what moves it between its states.

Written as SQL text rather than ORM models, for the reason `tenant_store` and
`settings_store` give: the product template defines none, and one feature
should not make the next inherit a mapper layer by default.

**Every move goes through `_advance`.** The state machine is in `koras_import`
and it refuses an edge that does not exist; doing the check here, before the
update, means a refusal names both states while the caller is still on the
stack — rather than an `UPDATE ... WHERE status = ?` that matches nothing and
reads as "the run disappeared".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from koras_import import (
    ImportTarget,
    ReadRefused,
    RowError,
    RunState,
    Validation,
    count_rows,
    decode,
    read_header,
    read_rows,
    require_move,
    resolve,
    sniff_delimiter,
    suggest,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: How many rows the preview reads. The shared data table paginates on the
#: client as of 2026-09-19, so a preview is a head of the file rather than the
#: file — and two hundred rows is enough to see whether a mapping is right.
PREVIEW = 200


@dataclass(frozen=True)
class Run:
    id: str
    target: str
    status: str
    format: str
    source_file_id: str
    delimiter: str
    encoding: str
    columns: tuple[str, ...]
    mapping: dict[str, str]
    operation: str
    rows_total: int
    rows_valid: int
    errors_total: int
    errors_cut: bool
    error: str | None
    requested_by: str
    committed_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @property
    def state(self) -> RunState:
        return RunState(self.status)


_COLUMNS = (
    "id, target, status, format, source_file_id, delimiter, encoding, columns, "
    "mapping, operation, rows_total, rows_valid, errors_total, errors_cut, "
    "error, requested_by, committed_by, created_at, started_at, finished_at"
)


def _run(row: Any) -> Run:  # noqa: ANN401 - a driver row, shaped by the select
    return Run(
        id=str(row.id),
        target=row.target,
        status=row.status,
        format=row.format,
        source_file_id=str(row.source_file_id),
        delimiter=row.delimiter,
        encoding=row.encoding,
        columns=tuple(row.columns or ()),
        mapping=dict(row.mapping or {}),
        operation=row.operation,
        rows_total=row.rows_total,
        rows_valid=row.rows_valid,
        errors_total=row.errors_total,
        errors_cut=row.errors_cut,
        error=row.error,
        requested_by=row.requested_by,
        committed_by=row.committed_by,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


async def create(
    session: AsyncSession,
    *,
    tenant_id: str,
    target: ImportTarget,
    source_file_id: str,
    requested_by: str,
    operation: str,
) -> Run:
    """Start a run against a file that is already uploaded and confirmed.

    The row is committed by the caller before anything reads the file, so a
    process that dies during analysis leaves a `created` run somebody can find
    rather than a request that vanished.
    """
    result = await session.execute(
        text(
            # `_COLUMNS` is a module constant; every value is bound.
            "insert into public.import_runs "  # noqa: S608
            "(tenant_id, target, source_file_id, requested_by, operation) "
            "values (:tenant_id, :target, cast(:file_id as uuid), :by, :operation) "
            f"returning {_COLUMNS}"
        ),
        {
            "tenant_id": tenant_id,
            "target": target.key,
            "file_id": source_file_id,
            "by": requested_by,
            "operation": operation,
        },
    )
    return _run(result.one())


async def get(session: AsyncSession, run_id: str) -> Run | None:
    """One run, scoped by row-level security rather than by a predicate here.

    The policy admits `tenant_id = current_tenant_id()`, so a query with no
    tenant clause returns this organisation's run or nothing. A hand-written
    predicate beside it would be a second place to get it wrong.
    """
    result = await session.execute(
        # `_COLUMNS` is a module constant and the id is bound. Every value a
        # caller supplies in this file is a parameter.
        text(
            f"select {_COLUMNS} from public.import_runs where id = cast(:id as uuid)"  # noqa: S608
        ),
        {"id": run_id},
    )
    row = result.first()
    return _run(row) if row is not None else None


async def recent(session: AsyncSession, *, limit: int = 50) -> list[Run]:
    result = await session.execute(
        text(
            f"select {_COLUMNS} from public.import_runs "  # noqa: S608 - a constant
            "order by created_at desc limit :limit"
        ),
        {"limit": max(1, min(limit, 200))},
    )
    return [_run(row) for row in result]


async def _advance(
    session: AsyncSession, run: Run, target: RunState, **columns: Any  # noqa: ANN401
) -> None:
    """Move a run, refusing an edge the machine does not have."""
    require_move(run.state, target)
    # The column *names* come from this module's own keyword arguments, never
    # from a caller, and every value is bound. A caller-supplied name could not
    # reach here without a function signature to arrive through.
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    clause = f", {assignments}" if assignments else ""
    await session.execute(
        text(
            f"update public.import_runs set status = :status{clause} "  # noqa: S608
            "where id = cast(:id as uuid)"
        ),
        {"status": target.value, "id": run.id, **columns},
    )


async def set_mapping(
    session: AsyncSession,
    run: Run,
    *,
    delimiter: str,
    encoding: str,
    columns: Sequence[str],
    mapping: Mapping[str, str],
) -> None:
    """Record what the file looks like and which column is which."""
    await _advance(
        session,
        run,
        RunState.MAPPED,
        delimiter=delimiter,
        encoding=encoding,
        columns=list(columns),
        mapping=json.dumps(dict(mapping)),
    )


async def begin_validation(session: AsyncSession, run: Run) -> None:
    await _advance(session, run, RunState.VALIDATING, started_at=datetime.now().astimezone())


async def cancel(session: AsyncSession, run: Run) -> None:
    await _advance(session, run, RunState.CANCELLED, finished_at=datetime.now().astimezone())


async def fail(session: AsyncSession, run: Run, reason: str) -> None:
    """A safe sentence for a person. Never a stack and never a provider body."""
    await _advance(
        session,
        run,
        RunState.FAILED,
        error=reason[:400],
        finished_at=datetime.now().astimezone(),
    )


async def record_validation(
    session: AsyncSession, run: Run, *, tenant_id: str, result: Validation
) -> RunState:
    """Store what the dry run found, and move the run accordingly.

    **Nothing of the target table is touched.** `validated` is a terminal state
    that wrote nothing, which is what makes a dry run a dry run rather than a
    promise.

    The previous report is cleared first: a second validation replaces the
    first, and two reports for one run is two answers to one question.
    """
    await session.execute(
        text("delete from public.import_row_errors where run_id = cast(:id as uuid)"),
        {"id": run.id},
    )
    for problem in result.errors:
        await session.execute(
            text(
                "insert into public.import_row_errors "
                "(run_id, tenant_id, row_number, column_name, field, code, value) "
                "values (cast(:run_id as uuid), :tenant_id, :row, :column, :field, "
                ":code, :value)"
            ),
            {
                "run_id": run.id,
                "tenant_id": tenant_id,
                "row": problem.row,
                "column": problem.column[:200],
                "field": problem.field[:200],
                "code": problem.code,
                "value": problem.value[:200],
            },
        )

    landed = RunState.VALIDATED if result.ok else RunState.VALIDATION_FAILED
    await _advance(
        session,
        run,
        landed,
        rows_total=result.rows,
        rows_valid=result.valid,
        errors_total=len(result.errors),
        errors_cut=result.truncated,
        finished_at=datetime.now().astimezone(),
    )
    return landed


async def errors(
    session: AsyncSession, run_id: str, *, limit: int = 100, after: int = 0
) -> list[RowError]:
    """A page of the report, in file order."""
    result = await session.execute(
        text(
            "select row_number, column_name, field, code, value "
            "from public.import_row_errors "
            "where run_id = cast(:id as uuid) and id > :after "
            "order by id limit :limit"
        ),
        {"id": run_id, "after": after, "limit": max(1, min(limit, 500))},
    )
    return [
        RowError(
            row=row.row_number,
            column=row.column_name,
            field=row.field,
            code=row.code,
            value=row.value,
        )
        for row in result
    ]


# ── reading the file ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Analysis:
    delimiter: str
    encoding: str
    columns: tuple[str, ...]
    suggested: dict[str, str]
    preview: list[dict[str, str]]
    rows_seen: int
    over_ceiling: bool
    #: True when characters could not be decoded and were replaced. The import
    #: proceeds; the run says so, and a customer wondering why one name looks
    #: wrong has an answer.
    replaced: bool


def analyse(raw: bytes, target: ImportTarget) -> Analysis:
    """What the file looks like, and a mapping to offer before anybody types.

    Pure: bytes in, an answer out. That is what lets the analysis be tested
    against the files real spreadsheets produce without a database or a bucket.
    """
    decoded = decode(raw)
    delimiter = sniff_delimiter(decoded.text)
    lines = decoded.text.splitlines(keepends=True)
    header = read_header(lines, delimiter=delimiter)
    rows = list(read_rows(lines, header=header, delimiter=delimiter, limit=PREVIEW))
    # Counted separately and bounded: the answer a caller needs is whether the
    # file is over the target's ceiling, not how far over.
    seen = count_rows(lines, delimiter=delimiter, ceiling=target.max_rows)
    return Analysis(
        delimiter=delimiter,
        encoding=decoded.encoding,
        columns=header.columns,
        suggested=suggest(target, header.columns),
        preview=[row.cells for row in rows],
        rows_seen=seen,
        over_ceiling=seen > target.max_rows,
        replaced=decoded.replaced,
    )


def check(raw: bytes, target: ImportTarget, run: Run) -> Validation:
    """The dry run itself: every row, one pass, every problem.

    Raises `ReadRefused` for a file that is not a table at all and
    `MappingRefused` for a mapping the target will not take — both of which are
    the run failing rather than the data being wrong, and the route and the job
    tell them apart.
    """
    decoded = decode(raw)
    lines = decoded.text.splitlines(keepends=True)
    header = read_header(lines, delimiter=run.delimiter)
    resolved = resolve(target, header.columns, run.mapping)
    rows = read_rows(
        lines, header=header, delimiter=run.delimiter, limit=target.max_rows
    )
    from koras_import import validate

    return validate(target, resolved, rows)


# ── the source file ──────────────────────────────────────────────────────────


class SourceRefused(RuntimeError):
    """The file behind a run cannot be read, and the reason is not the data."""


#: Scan states an import will not parse.
#:
#: **Narrower than a download, deliberately.** `core/file_scan.py` withholds
#: `infected` alone and lets a `pending` file be downloaded, which is a decision
#: taken so that a product with no scanner is not broken -- a person choosing to
#: open a file they uploaded is making their own judgement. Parsing is not that:
#: the product reads the bytes itself and writes rows from them, unattended, and
#: "nobody has looked at this yet" is not a state to do that in.
#:
#: `skipped` is refused for the same reason and is the state a scanner reports
#: when it declined to look -- an answer, and not a clean one.
#:
#: This needs no scanner to exist. With none configured every file is `pending`,
#: so a product without one cannot import at all, which is the honest position:
#: an import is the one surface where a product parses a stranger's file.
UNPARSEABLE_SCANS: frozenset[str] = frozenset({"pending", "skipped", "infected"})

_SOURCE = text(
    "select storage_key, size_bytes, status, scan_status, name "
    "from public.files where id = cast(:id as uuid)"
)


async def source_bytes(session: AsyncSession, store: Any, file_id: str) -> bytes:  # noqa: ANN401
    """The uploaded file, or a refusal saying which of four things was wrong.

    Held whole in memory, and bounded by the upload ceiling rather than by
    hope. Phase 4 streams; this is the caller a streaming reader will replace,
    and the reader it hands rows to already streams, so that change is here and
    not in `koras_import`.
    """
    row = (await session.execute(_SOURCE, {"id": file_id})).first()
    if row is None:
        raise SourceRefused("import.source.missing")
    if row.status != "ready":
        raise SourceRefused("import.source.not_ready")
    if (row.scan_status or "pending") in UNPARSEABLE_SCANS:
        raise SourceRefused("import.source.unscanned")
    try:
        return await store.get(row.storage_key)  # type: ignore[no-any-return]
    except Exception as error:  # noqa: BLE001 - the provider's own type is not ours
        logger.exception("the source file for an import could not be read")
        raise SourceRefused("import.source.unreadable") from error


__all__ = [
    "PREVIEW",
    "Analysis",
    "ReadRefused",
    "Run",
    "SourceRefused",
    "UNPARSEABLE_SCANS",
    "analyse",
    "begin_validation",
    "cancel",
    "check",
    "create",
    "errors",
    "fail",
    "get",
    "record_validation",
    "recent",
    "source_bytes",
    "set_mapping",
]
