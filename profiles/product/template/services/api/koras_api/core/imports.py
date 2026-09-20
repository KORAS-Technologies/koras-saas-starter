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

from koras_audit import AuditAction, Classification, actions
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


# ── what this capability records ─────────────────────────────────────────────
#
# Registered here, by the module the capability owns, the way storage registers
# its own and the assistant registers its notification kind. A product without
# `data_import` declares none of these.
#
# **Three actions, and the commit outcome is deliberately not one of them.** The
# writing happens in a worker, and `core/audit` reaches `core/database`, which
# reaches the API's own `Settings()` -- so auditing the outcome from the worker
# would mean the worker satisfying the API's whole configuration surface to
# write one row. What the worker produces instead is the run itself: `status`,
# `error`, the three counts, `committed_by` and `finished_at`, on a row that is
# queryable, tenant-scoped and retained. The security-relevant fact -- who
# authorised a write of somebody's records, against which target, under which
# operation -- is known in the request, and that is what is audited here.
#
# It is written down rather than left to be noticed because "every import
# attributable and audited" is a story (IMPORT-US-016), and half of it is met
# by a table rather than by the audit log.
IMPORT_ACTIONS = (
    AuditAction(
        key="import.run.started",
        classification=Classification.ACTIVITY,
        summary="An import run was created against a target, before any mapping.",
    ),
    AuditAction(
        key="import.run.committed",
        classification=Classification.AUDIT,
        summary=(
            "A person confirmed a checked import run, authorising it to write "
            "records. The run row records what was written."
        ),
    ),
    AuditAction(
        key="import.run.refused",
        classification=Classification.SECURITY,
        summary="A commit was refused: the target accepts no writer, or the run could not move.",
    ),
)

for _action in IMPORT_ACTIONS:
    actions.add(_action)


@dataclass(frozen=True)
class Run:
    id: str
    target: str
    status: str
    format: str
    #: None once retention has purged the file. The run survives it — what it
    #: remembers about the import is on this row, not in the bytes — and every
    #: route that needs the file answers `import.source.missing`.
    source_file_id: str | None
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
        source_file_id=str(row.source_file_id) if row.source_file_id else None,
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


async def request_commit(session: AsyncSession, run: Run, *, by: str) -> None:
    """A person has confirmed. The worker has not started.

    The second actor, and the reason this table is not an export: `committed_by`
    is written here rather than at the end, because the fact worth recording is
    *who decided*, and a run that failed while committing still had somebody
    decide it.
    """
    await _advance(session, run, RunState.COMMIT_REQUESTED, committed_by=by)


async def begin_commit(session: AsyncSession, run: Run) -> None:
    await _advance(session, run, RunState.COMMITTING, started_at=datetime.now().astimezone())


async def record_commit(
    session: AsyncSession, run: Run, *, created: int, updated: int, skipped: int
) -> None:
    """Mark a run committed, in the same transaction that wrote its rows.

    **Deliberately not its own transaction.** If this commits and the rows do
    not, the run claims an import that did not happen; if the rows commit and
    this does not, the run can be committed again and the rows go in twice.
    One transaction is what makes neither possible, and it is why the caller
    passes the session it wrote with rather than opening another.
    """
    await _advance(
        session,
        run,
        RunState.COMMITTED,
        rows_total=created + updated + skipped,
        rows_valid=created + updated,
        finished_at=datetime.now().astimezone(),
    )


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


def _parse(raw: bytes, target: ImportTarget, run: Run) -> tuple[Any, list[Any]]:
    """The mapping and the rows, resolved once. Shared by the dry run and the commit.

    One reader for both passes on purpose: a commit that parsed differently
    from the validation that approved it would write rows nobody checked, and
    the difference would be invisible -- both would look like they had run.
    """
    decoded = decode(raw)
    lines = decoded.text.splitlines(keepends=True)
    header = read_header(lines, delimiter=run.delimiter)
    resolved = resolve(target, header.columns, run.mapping)
    rows = list(
        read_rows(lines, header=header, delimiter=run.delimiter, limit=target.max_rows)
    )
    return resolved, rows


def check(raw: bytes, target: ImportTarget, run: Run) -> Validation:
    """The dry run itself: every row, one pass, every problem.

    Raises `ReadRefused` for a file that is not a table at all and
    `MappingRefused` for a mapping the target will not take -- both of which are
    the run failing rather than the data being wrong, and the route and the job
    tell them apart.
    """
    from koras_import import validate

    resolved, rows = _parse(raw, target, run)
    return validate(target, resolved, rows)


def prepare(
    raw: bytes, target: ImportTarget, run: Run
) -> tuple[Validation, tuple[Mapping[str, str], ...]]:
    """What to write, and the verdict that says whether it may be.

    **The file is validated again here**, rather than the commit trusting the
    verdict the dry run stored. It costs one pass over a file already bounded by
    the target's ceiling, and it closes the gap between "somebody checked this"
    and "this is what goes in": between the two, a deploy may have changed the
    target's own field specifications, and the run's stored counts would still
    say it was clean.

    Both are returned rather than one raising, because the caller wants to say
    *which* rows are wrong, and a refusal carrying a sentence cannot.
    """
    from koras_import import validate

    resolved, rows = _parse(raw, target, run)
    verdict = validate(target, resolved, rows)
    mapped = tuple(
        {field: row.cells.get(column, "").strip() for field, column in resolved.fields.items()}
        for row in rows
    )
    return verdict, mapped


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

#: The largest source file this phase will read.
#:
#: **Not the upload ceiling**, which is what this used to rely on: `source_bytes`
#: selected `size_bytes` and never looked at it, and its docstring claimed the
#: read was "bounded by the upload ceiling rather than by hope" -- a ceiling
#: whose default is five thousand megabytes. Two concurrent analyses of a four
#: gigabyte upload take the API process out, and the route that does it is
#: reachable by any member with `imports.manage` pressing a button twice.
#: IMP-02 in `docs/features/data-import/review.md`.
#:
#: Sixty-four mebibytes is far above fifty thousand rows at any realistic width
#: and far below anything that threatens the process. Phase 4 streams and this
#: constant goes with it; until then the bound is a number rather than a hope.
MAX_SOURCE_BYTES = 64 * 1024 * 1024

_SOURCE = text(
    "select storage_key, size_bytes, status, scan_status, name "
    "from public.files where id = cast(:id as uuid)"
)


async def check_source(session: AsyncSession, file_id: str | None) -> Any:  # noqa: ANN401
    """Everything that can be known about a source without fetching it.

    Split out so the same four refusals answer at `POST /imports`, where a
    person has chosen a file and nothing else yet, as well as at the two routes
    that read it. Being told at the start beats being told after forty columns
    have been mapped.
    """
    if not file_id:
        # Purged by retention, which is a thing that now happens: the foreign
        # key is `on delete set null` precisely so an import cannot make a
        # customer's file immortal.
        raise SourceRefused("import.source.missing")
    row = (await session.execute(_SOURCE, {"id": file_id})).first()
    if row is None:
        raise SourceRefused("import.source.missing")
    if row.status != "ready":
        raise SourceRefused("import.source.not_ready")
    if (row.scan_status or "pending") in UNPARSEABLE_SCANS:
        raise SourceRefused("import.source.unscanned")
    if int(row.size_bytes or 0) > MAX_SOURCE_BYTES:
        raise SourceRefused("import.source.too_large")
    return row


async def source_bytes(session: AsyncSession, store: Any, file_id: str | None) -> bytes:  # noqa: ANN401
    """The uploaded file, or a refusal saying which of five things was wrong.

    Held whole in memory, and bounded by `MAX_SOURCE_BYTES` -- checked against
    the size the index recorded, **before** the object is fetched, so an
    oversized file costs a row read rather than a transfer. Phase 4 streams;
    this is the caller a streaming reader will replace, and the reader it hands
    rows to already streams, so that change is here and not in `koras_import`.
    """
    row = await check_source(session, file_id)
    try:
        return await store.get(row.storage_key)  # type: ignore[no-any-return]
    except Exception as error:  # noqa: BLE001 - the provider's own type is not ours
        logger.exception("the source file for an import could not be read")
        raise SourceRefused("import.source.unreadable") from error


__all__ = [
    "MAX_SOURCE_BYTES",
    "PREVIEW",
    "Analysis",
    "ReadRefused",
    "Run",
    "SourceRefused",
    "UNPARSEABLE_SCANS",
    "analyse",
    "begin_commit",
    "begin_validation",
    "check_source",
    "cancel",
    "check",
    "create",
    "errors",
    "fail",
    "get",
    "record_commit",
    "record_validation",
    "request_commit",
    "recent",
    "source_bytes",
    "set_mapping",
]
