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

import asyncio
import hashlib
import json
import logging
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from koras_audit import AuditAction, Classification, actions
from koras_import import (
    Candidate,
    Candidates,
    Compatibility,
    Format,
    ImportTarget,
    Operation,
    Prediction,
    PreflightRefused,
    ReadRefused,
    ResolvedMapping,
    RowError,
    RowStream,
    RunState,
    SafetyLimits,
    Validation,
    compare,
    inspect_source,
    normaliser,
    open_rows,
    predict_from,
    request_from,
    require_move,
    resolve,
    suggest,
    validate,
    with_rejections,
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
    # The three below arrived with the templates on 2026-09-29. Two of them are
    # written by the worker, which reverses the Phase 2 position that the run
    # row is the only record of an outcome: it still is the *state*, and these
    # are the evidence that a moment happened, carrying counts and never a
    # cell. ADR 0012 D5.
    AuditAction(
        key="import.template.downloaded",
        classification=Classification.ACTIVITY,
        summary="A person downloaded a template for a target, in a format, at a version.",
    ),
    AuditAction(
        key="import.run.validated",
        classification=Classification.ACTIVITY,
        summary=(
            "A dry run finished. Outcome ok means every row passed; error means "
            "the report lists problems. The counts are in the details."
        ),
    ),
    AuditAction(
        key="import.run.finished",
        classification=Classification.AUDIT,
        summary=(
            "A confirmed import finished. Outcome ok carries what was written; "
            "error carries the safe sentence the run records."
        ),
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
    #: Everything below is nullable where a run from before 2026-09-29 cannot
    #: know it. A default of zero would render three false figures for every
    #: such run; null renders the sentence the page drew before.
    template_version: int | None = None
    job_id: str | None = None
    rows_duplicate: int = 0
    predicted_create: int | None = None
    predicted_update: int | None = None
    predicted_skip: int | None = None
    rows_created: int | None = None
    rows_updated: int | None = None
    rows_skipped: int | None = None
    #: From the file row, when it still exists. Read by a join, never stored
    #: twice.
    source_name: str | None = None
    source_bytes: int | None = None

    @property
    def state(self) -> RunState:
        return RunState(self.status)

    @property
    def written(self) -> tuple[int, int, int] | None:
        if self.rows_created is None or self.rows_updated is None or self.rows_skipped is None:
            return None
        return (self.rows_created, self.rows_updated, self.rows_skipped)


_COLUMNS = (
    "id, target, status, format, source_file_id, delimiter, encoding, columns, "
    "mapping, operation, rows_total, rows_valid, errors_total, errors_cut, "
    "error, requested_by, committed_by, created_at, started_at, finished_at, "
    "template_version, job_id, rows_duplicate, predicted_create, predicted_update, "
    "predicted_skip, rows_created, rows_updated, rows_skipped"
)

#: The same columns qualified, plus the source's name and size from `files`.
#: A left join: a run whose file retention purged still lists, with nulls.
#: Row-level security on `files` applies to the joined row exactly as it does
#: to a direct read, so nothing crosses a tenant here that could not before.
_SELECT = (
    "select " + ", ".join(f"r.{name}" for name in _COLUMNS.split(", ")) + ", "
    "f.name as source_name, f.size_bytes as source_bytes "
    "from public.import_runs r left join public.files f on f.id = r.source_file_id"
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
        template_version=row.template_version,
        job_id=row.job_id,
        rows_duplicate=row.rows_duplicate or 0,
        predicted_create=row.predicted_create,
        predicted_update=row.predicted_update,
        predicted_skip=row.predicted_skip,
        rows_created=row.rows_created,
        rows_updated=row.rows_updated,
        rows_skipped=row.rows_skipped,
        source_name=getattr(row, "source_name", None),
        source_bytes=getattr(row, "source_bytes", None),
    )


async def create(
    session: AsyncSession,
    *,
    tenant_id: str,
    target: ImportTarget,
    source_file_id: str,
    requested_by: str,
    operation: str,
    format: Format = Format.CSV,  # noqa: A002 - the column's name
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
            "(tenant_id, target, source_file_id, requested_by, operation, format) "
            "values (:tenant_id, :target, cast(:file_id as uuid), :by, :operation, "
            f":format) returning {_COLUMNS}"
        ),
        {
            "tenant_id": tenant_id,
            "target": target.key,
            "file_id": source_file_id,
            "by": requested_by,
            "operation": operation,
            # The column was always its default until 2026-09-29: this insert
            # never named it, so every run said `csv` whatever it read.
            "format": format.value,
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
        text(f"{_SELECT} where r.id = cast(:id as uuid)"),  # noqa: S608 - a constant
        {"id": run_id},
    )
    row = result.first()
    return _run(row) if row is not None else None


async def recent(session: AsyncSession, *, limit: int = 50) -> list[Run]:
    result = await session.execute(
        text(f"{_SELECT} order by r.created_at desc limit :limit"),  # noqa: S608 - a constant
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


async def set_job(session: AsyncSession, run: Run, job_id: str) -> None:
    """Remember the queue's id for the last job this run was handed to.

    Not through `_advance`: no state changes, and the id is written *after*
    the enqueue answers, so a run in `validating` with no job id is one whose
    enqueue was refused before it could be recorded.
    """
    await session.execute(
        text("update public.import_runs set job_id = :job_id where id = cast(:id as uuid)"),
        {"job_id": job_id[:200], "id": run.id},
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


async def abandon(session: AsyncSession, run: Run, reason: str) -> bool:
    """`fail`, for a job that was stopped from outside. True if the run moved.

    **The update names the status it expects, and that is the difference from
    `fail`.** A handler that fails a run does so on the session that did the
    work, knowing what state the run is in. A job cancelled by its queue does
    not know: the cancellation may have landed while the commit's one
    transaction was on its way to the database. If that transaction commits,
    the run is `committed` and its rows are written, and an unguarded update
    arriving a moment later would say `failed` over an import that happened.
    With the status in the predicate the update waits for that transaction
    and then matches nothing.
    """
    require_move(run.state, RunState.FAILED)
    result = await session.execute(
        text(
            "update public.import_runs set status = :status, error = :error, "
            "finished_at = :finished_at where id = cast(:id as uuid) and status = :was"
        ),
        {
            "status": RunState.FAILED.value,
            "error": reason[:400],
            "finished_at": datetime.now().astimezone(),
            "id": run.id,
            "was": run.status,
        },
    )
    return bool(getattr(result, "rowcount", 0) == 1)


async def record_validation(
    session: AsyncSession,
    run: Run,
    *,
    tenant_id: str,
    result: Validation,
    prediction: Prediction | None = None,
    template_version: int | None = None,
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
        rows_duplicate=result.duplicates,
        # Null when the target declares no matcher: the page then says the
        # figures are unknown rather than drawing three zeros.
        predicted_create=prediction.create if prediction else None,
        predicted_update=prediction.update if prediction else None,
        predicted_skip=prediction.skip if prediction else None,
        template_version=template_version,
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
        # Kept apart as well as summed. The sum was all the row held until
        # 2026-09-29, and "wrote 920 of 1000" cannot say which were new.
        rows_created=created,
        rows_updated=updated,
        rows_skipped=skipped,
        finished_at=datetime.now().astimezone(),
    )


@dataclass(frozen=True)
class Reported:
    """One problem, and the cursor that reaches the next one.

    **The cursor is the table's own key, and it used to be unreachable.** This
    paged on `id > :after` and returned every column *except* `id`, so the only
    number a caller had to send back was the file's row number -- a different
    scale entirely, global identity against a per-file count. The report
    download therefore stopped early on a young database and repeated pages on
    an old one, silently, while telling the customer it contained every
    problem. IMP2-05 in `docs/features/data-import/phase-2-review.md`.

    Named rather than folded into `RowError` because `RowError` is the engine's,
    produced by validation before any row exists to have a key.
    """

    cursor: int
    problem: RowError


async def errors(
    session: AsyncSession, run_id: str, *, limit: int = 100, after: int = 0
) -> list[Reported]:
    """A page of the report, in the order the rows were recorded."""
    result = await session.execute(
        text(
            "select id, row_number, column_name, field, code, value "
            "from public.import_row_errors "
            "where run_id = cast(:id as uuid) and id > :after "
            "order by id limit :limit"
        ),
        {"id": run_id, "after": after, "limit": max(1, min(limit, 500))},
    )
    return [
        Reported(
            cursor=row.id,
            problem=RowError(
                row=row.row_number,
                column=row.column_name,
                field=row.field,
                code=row.code,
                value=row.value,
            ),
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
    format: Format = Format.CSV
    #: The workbook sheet that was read; None for a CSV.
    sheet: str | None = None
    #: The template identity the file carried; None for a CSV and for any
    #: file not made from a template.
    identity: str | None = None
    #: The header judged against the target as declared today. ADR 0012.
    template: Compatibility | None = None


#: What `files` says about a source's format, from its name first and its
#: content type second. A spreadsheet's own content type is unambiguous; a
#: CSV arrives as text/csv, text/plain, application/vnd.ms-excel and worse,
#: so the extension is what a person sees and what decides.
_WORKBOOK_TYPES = frozenset(
    {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
)


def source_format(name: str | None, content_type: str | None) -> Format:
    """The format a source file is in, as far as its row can say."""
    suffix = (name or "").rpartition(".")[2].lower()
    if suffix == "xlsx":
        return Format.XLSX
    if suffix in {"csv", "tsv", "txt"}:
        return Format.CSV
    if suffix == "json":
        return Format.JSON
    if (content_type or "").split(";")[0].strip().lower() in _WORKBOOK_TYPES:
        return Format.XLSX
    return Format.CSV


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
#:
#: **"Far below anything that threatens the process" was wrong**, and GR-352
#: measured by how much on 2026-10-01: a file inside this ceiling took a worker
#: past 1.4 GiB. The transfer is what this bounds. What the bytes become is
#: bounded by `SAFETY_LIMITS` below.
MAX_SOURCE_BYTES = 64 * 1024 * 1024

#: The envelope every source must fit **before** a reader is handed it.
#:
#: The same object for the API and the worker, so there is one answer to
#: whether a file is safe. Everything in it but the source ceiling is an
#: interim GR-352 default from `koras_import.safety`, not a ratified limit:
#: a product that has measured its own envelope replaces this, and the NFR
#: decision GR-352 is waiting on will replace the defaults themselves.
SAFETY_LIMITS = SafetyLimits(max_source_bytes=MAX_SOURCE_BYTES)


def limits_for(target: ImportTarget, *, rows: bool) -> SafetyLimits:
    """The envelope for one read of one target's file.

    `rows` says whether the safety pass refuses a file over the target's row
    ceiling. The dry run and the commit ask it to: they would otherwise read
    `max_rows` rows of a longer file and say nothing about the rest. The
    analysis does not, because it has its own answer -- `over_ceiling`, which
    the mapping route turns into a refusal -- and a route that answered 200
    yesterday should not answer 422 today for a file that threatens nothing.
    """
    return replace(SAFETY_LIMITS, max_rows=target.max_rows if rows else None)


def analyse(
    raw: bytes, target: ImportTarget, fmt: Format = Format.CSV, *, sample: int = PREVIEW
) -> Analysis:
    """What the file looks like, and a mapping to offer before anybody types.

    Pure: bytes in, an answer out. That is what lets the analysis be tested
    against the files real spreadsheets produce without a database or a bucket.

    **Neither whole-file reader is called.** Until GR-352B this parsed the
    whole file the way the dry run then did -- `read_workbook`, and `decode`
    into one string -- to keep two hundred rows of it. `inspect_source`
    streams the head instead: the header, up to `sample` rows, and a count
    that stops past the target's ceiling. The dry run and the commit read
    through `_parse`, and what they read is what is validated and written.

    **The safety pass runs first, for both formats**, inside `inspect_source`,
    so there is no way to reach the inspection without it.

    `sample=0` is the mapping route's: it needs the header and whether the
    file is over the ceiling, and no rows at all.

    **Synchronous, and never called from the event loop.** A file inside the
    envelope can still take seconds to walk. A route awaits `analysed`.
    """
    found = inspect_source(
        raw, fmt, limits_for(target, rows=False), sample=sample, ceiling=target.max_rows
    )
    columns = found.header.columns
    if found.sample_cut:
        # Counts and never a cell. The preview is shorter than it could have
        # been because the next row would have passed the sample's character
        # budget; the response has no field to say so, and adding one is a
        # contract change GR-352B did not make.
        logger.info(
            "an import preview stopped at its character budget: %d of up to %d rows, "
            "target %s",
            len(found.rows),
            sample,
            target.key,
        )
    return Analysis(
        delimiter=found.delimiter,
        encoding=found.encoding,
        columns=columns,
        suggested=suggest(target, columns),
        preview=[row.cells for row in found.rows],
        rows_seen=found.rows_seen,
        over_ceiling=found.over_ceiling,
        replaced=found.replaced,
        format=fmt,
        sheet=found.sheet,
        identity=found.identity,
        # A CSV carries no identity, so there is none to judge there and the
        # verdict is the header's alone -- what it always was.
        template=compare(target, columns, found=found.identity),
    )


async def analysed(
    raw: bytes, target: ImportTarget, fmt: Format = Format.CSV, *, sample: int = PREVIEW
) -> Analysis:
    """`analyse`, on a worker thread, for a caller that is on the event loop.

    The inspection is bounded in memory and not in time: it is Python handling
    one parser event after another, and a file at the edge of the envelope is
    several seconds of it. Run inline, every other request this process is
    serving waits for those seconds -- GR-352 measured 126 of them. On a
    thread the loop keeps turning; the interpreter lock is shared, so the
    other requests are slower while it runs rather than stopped.

    `asyncio.to_thread`, which is what `core/knowledge.py` already does for
    its own CPU-bound read. No queue and no job: an analysis stores nothing,
    and somebody is waiting for the answer.
    """
    return await asyncio.to_thread(analyse, raw, target, fmt, sample=sample)


def _needs_match_keys(run: Run) -> bool:
    """Every operation but a plain create recognises rows, and needs its keys mapped."""
    return run.operation != Operation.CREATE.value


#: What a caller hands down to be asked, as the file is walked, whether the
#: work should go on. `koras_import.WorkBudget.check` is the worker's.
Watch = Callable[[], None]


def _parse(
    raw: bytes, target: ImportTarget, run: Run, watch: Watch | None = None
) -> tuple[ResolvedMapping, RowStream]:
    """The mapping, and the rows as a stream. Shared by the dry run and the commit.

    One reader for both passes on purpose: a commit that parsed differently
    from the validation that approved it would write rows nobody checked, and
    the difference would be invisible -- both would look like they had run.

    **The rows are not a list.** Until GR-352C this returned every row of the
    file, read through `read_workbook` or a whole-file `decode`, and the
    caller went through them two or three times. `open_rows` yields them as
    the file is walked, so a caller takes what it needs of a row in the one
    pass `validate` makes, and what is held at any moment is what the safety
    envelope already bounds rather than a second and third copy of the file.
    `docs/features/data-import/worker-resource-envelope.md` has what that
    was measured at.

    The safety pass is inside `open_rows`, by the same envelope the analysis
    used. This is the one function the dry run and the commit both come
    through, so a file that is not safe reaches neither.
    """
    limits = limits_for(target, rows=True)
    workbook = run.format == Format.XLSX.value
    stream = open_rows(
        raw,
        Format.XLSX if workbook else Format.CSV,
        limits,
        limit=target.max_rows,
        delimiter=None if workbook else run.delimiter,
        watch=watch,
    )
    try:
        resolved = resolve(
            target,
            stream.header.columns,
            run.mapping,
            require_match_keys=_needs_match_keys(run),
        )
    except BaseException:
        # The stream holds the workbook open until it is read to its end.
        stream.close()
        raise
    return resolved, stream


@dataclass(frozen=True)
class Examined:
    """A dry run's three products, for a caller that goes on to predict."""

    resolved: ResolvedMapping
    verdict: Validation
    #: What the dry run kept of the rows it passed: a key, a row number and
    #: one cell each. The rows themselves have gone by -- GR-352C.
    candidates: Candidates
    #: The version the file's template identity named for this target, or None.
    template_version: int | None = None


def examine(
    raw: bytes, target: ImportTarget, run: Run, *, watch: Watch | None = None
) -> Examined:
    """`check`, keeping the mapping and what a matcher needs to be asked.

    One pass over the file. What is kept of a row the validator passed is its
    match key, its number and the one cell a rejection quotes; of a row it
    did not pass, its problems, up to the report's own ceiling.

    **Synchronous, and never called from the event loop** by a worker: it is
    seconds of parsing for a file at the edge of the envelope, and a worker
    whose loop is held answers no heartbeat and runs no other job.
    """
    resolved, stream = _parse(raw, target, run, watch)
    try:
        found = stream.identity
        gathered = Candidate(target, resolved)
        verdict = validate(target, resolved, stream, each=gathered.collect)
    finally:
        stream.close()
    version = compare(target, (), found=found).version_found if found else None
    return Examined(
        resolved=resolved,
        verdict=verdict,
        candidates=gathered.candidates(),
        template_version=version,
    )


async def predict_outcome(
    session: AsyncSession,
    *,
    target: ImportTarget,
    run: Run,
    tenant_id: str,
    examined: Examined,
) -> tuple[Validation, Prediction | None]:
    """Ask the target's matcher once, and count what the operation would do.

    None when the target declares no matcher: the page then says the figures
    are unknown. The call runs in a savepoint, so a matcher that raises leaves
    the run's own rows intact -- catching an exception from a shared session
    isolates the caller from the exception and not from the transaction.

    With `create`, a row that names an existing record is a row error from
    here on, and the verdict returned carries it. ADR 0012 D9.
    """
    if target.matcher is None:
        return examined.verdict, None
    request = request_from(target, examined.candidates, tenant_id=tenant_id)
    async with session.begin_nested():
        existing = await target.matcher(session, request)
    prediction = predict_from(
        target,
        Operation(run.operation),
        examined.resolved,
        examined.candidates,
        existing=existing,
    )
    return with_rejections(examined.verdict, prediction), prediction


def check(raw: bytes, target: ImportTarget, run: Run) -> Validation:
    """The dry run itself: every row, one pass, every problem.

    Raises `ReadRefused` for a file that is not a table at all and
    `MappingRefused` for a mapping the target will not take -- both of which are
    the run failing rather than the data being wrong, and the route and the job
    tell them apart.
    """
    resolved, stream = _parse(raw, target, run)
    try:
        return validate(target, resolved, stream)
    finally:
        stream.close()


def prepare(
    raw: bytes, target: ImportTarget, run: Run, *, watch: Watch | None = None
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

    **One pass, and one dictionary a row.** The writer's contract is every row
    of the run at once, so every row's dictionary is held when the writer is
    called -- that much is the commit's own cost and stays. What GR-352C
    removed is everything that used to be held beside it: the parsed rows,
    which were a second dictionary for every row, and the file as text. Each
    dictionary is built from its row while `validate` still has the row, and
    the row is then gone. Synchronous, like `examine`, and for its reason.
    """
    resolved, stream = _parse(raw, target, run, watch)
    # Canonical, not raw: a date the validator accepted as `31.12.2025` reaches
    # the writer as `2025-12-31`, a decimal with a point, a boolean as `true`.
    # The same function the matcher's keys go through. IMP2-19.
    normalise = normaliser(target, resolved)
    mapped: list[Mapping[str, str]] = []
    try:
        verdict = validate(
            target,
            resolved,
            stream,
            each=lambda row, _key, _bad: mapped.append(normalise(row)),
        )
    finally:
        stream.close()
    return verdict, tuple(mapped)


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
    "select storage_key, size_bytes, status, scan_status, name, content_type, category, "
    "checksum_sha256, checksum_verified_at "
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


def _fetch(store: Any, row: Any) -> bytes:  # noqa: ANN401
    """The object the index row describes, or a refusal. Synchronous.

    `ObjectStore` is a synchronous protocol -- boto3 underneath -- so this is
    the half of `source_bytes` that runs on a thread.

    **The row is what was validated, so the object is held to it.** The size
    was compared with the bucket's own answer when the upload was confirmed,
    and it is what `check_source` measured against `MAX_SOURCE_BYTES`. An
    object that no longer has that size is not the file somebody mapped, and
    one that has grown is a transfer the ceiling never agreed to -- so the
    bucket is asked before the bytes are, and the bytes are counted after.
    Where the provider corroborated a SHA-256 at confirmation, the bytes are
    held to that as well; a digest that was only ever claimed proves nothing
    and is not compared.
    """
    size = int(row.size_bytes or 0)
    found = store.head(row.storage_key)
    if found is None:
        raise SourceRefused("import.source.missing")
    if found != size:
        raise SourceRefused("import.source.changed")
    raw = store.get(row.storage_key)
    if raw is None:
        # Deleted between the two calls.
        raise SourceRefused("import.source.missing")
    if not isinstance(raw, bytes):
        raise TypeError(f"the object store answered {type(raw).__name__}, not bytes")
    if len(raw) != size:
        raise SourceRefused("import.source.changed")
    digest = getattr(row, "checksum_sha256", None)
    if digest and getattr(row, "checksum_verified_at", None) is not None:
        if hashlib.sha256(raw).hexdigest() != digest:
            raise SourceRefused("import.source.changed")
    return raw


async def source_bytes(session: AsyncSession, store: Any, file_id: str | None) -> bytes:  # noqa: ANN401
    """The uploaded file, or a refusal saying which of six things was wrong.

    Held whole in memory, and bounded by `MAX_SOURCE_BYTES` -- checked against
    the size the index recorded, **before** the object is fetched, so an
    oversized file costs a row read rather than a transfer. Phase 4 streams;
    this is the caller a streaming reader will replace, and the reader it hands
    rows to already streams, so that change is here and not in `koras_import`.

    **The store is called on a thread, and is not awaited.** Until
    IMPORT-DEF-014 this awaited `store.get`, and `S3ObjectStore.get` is a plain
    function: against a real bucket the object was fetched on the event loop
    and the `await` of its bytes then raised, so every import answered
    `import.source.unreadable`. Every test passed, because every test handed
    in a store whose `get` was a coroutine. The doubles are synchronous now,
    like the thing they stand for.

    A cancelled caller stops waiting and the thread finishes its transfer: at
    most one source, which is what the slot or the heavy gate the caller holds
    already counts.
    """
    row = await check_source(session, file_id)
    try:
        return await asyncio.to_thread(_fetch, store, row)
    except SourceRefused:
        raise
    except Exception as error:  # noqa: BLE001 - the provider's own type is not ours
        logger.exception("the source file for an import could not be read")
        raise SourceRefused("import.source.unreadable") from error


# ── how many analyses at once ────────────────────────────────────────────────

#: PROVISIONAL (GR-352C, pending NFR ratification). How many analyses one API
#: process runs at a time, each holding the source it fetched.
#:
#: An analysis is cheap -- GR-352B measured it at under seven mebibytes over
#: its file -- and the file is not: it is fetched whole, up to
#: `MAX_SOURCE_BYTES`, before the inspection starts, and held until the
#: inspection ends. Nothing bounded how many requests did that at once, so
#: eight people opening a mapping page for a large file was eight sources in
#: one 512 MB process. IMPORT-GAP-019. Two is 128 MiB of sources at the worst,
#: beside whatever else the process is serving.
#:
#: Per process, which is the scope the memory has. A request past the limit
#: waits its turn holding nothing; it is not refused.
ANALYSIS_SLOTS = 2

_analysis_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def analysis_slot() -> asyncio.Semaphore:
    """The gate a route holds from before it fetches a source until it has
    answered: `async with store.analysis_slot(): ...`.

    One semaphore for each event loop, made on first use, because a semaphore
    belongs to the loop it first waited on and a test suite runs many loops.
    """
    loop = asyncio.get_running_loop()
    slot = _analysis_slots.get(loop)
    if slot is None:
        slot = _analysis_slots[loop] = asyncio.Semaphore(ANALYSIS_SLOTS)
    return slot


__all__ = [
    "ANALYSIS_SLOTS",
    "MAX_SOURCE_BYTES",
    "PREVIEW",
    "SAFETY_LIMITS",
    "Analysis",
    "Examined",
    "PreflightRefused",
    "ReadRefused",
    "Reported",
    "Run",
    "SourceRefused",
    "UNPARSEABLE_SCANS",
    "abandon",
    "analyse",
    "analysed",
    "analysis_slot",
    "begin_commit",
    "examine",
    "limits_for",
    "predict_outcome",
    "set_job",
    "source_format",
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
