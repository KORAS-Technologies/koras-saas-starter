"""Loading a file of records into a table this product owns.

Six routes and one rule: **nothing here writes a row of a target table.** Phase
1 is upload, map, dry run — the run reaches `validated`, which is a terminal
state that wrote nothing, and a person looks at what would have happened. The
commit is Phase 2 and has its own route, its own confirmation and its own
actor.

**`imports.manage` on every route, reads included.** A run names a customer's
own records and the mapping shows their column headings, so the history is not
less sensitive than the act. The permission is administrative and is held by
owners and administrators alone.

**The allowlist is the mapping check.** A mapping arrives from a browser and
names target fields; `resolve` refuses one the target never declared rather
than dropping it, because dropping it is how an import writes a column it was
never meant to reach. That refusal is a 422 with the field named, so a caller
who mistyped is told rather than being answered 200 by a request that changed
nothing.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from koras_auth import JWTClaims
from koras_auth.permissions import permissions_for
from koras_import import (
    COMMIT_RUN,
    VALIDATE_RUN,
    ImportTarget,
    MappingRefused,
    Operation,
    ReadRefused,
    RunState,
    may_move,
)
from pydantic import BaseModel, Field

from ..core import imports as store
from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.jobs import JobsDep
from ..core.storage import StorageDep
from ..core.tenant import TenantDep, require_subject
from ..imports import registry

router = APIRouter(tags=["imports"])

MANAGE_PERMISSION = "imports.manage"


def _require(claims: JWTClaims, doing: str) -> None:
    if MANAGE_PERMISSION not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            f"{doing} needs the {MANAGE_PERMISSION} permission",
        )


def _require_target(claims: JWTClaims, target: ImportTarget) -> None:
    """A target's own permission, on top of `imports.manage`.

    `ImportTarget.permission` says what writing *these* records needs, and a
    declaration nothing enforces would be worse than none at all: it reads like
    a gate. Checked here rather than in the package, because the package has no
    caller. Both are required -- a target cannot widen access by declaring a
    permission everybody holds.
    """
    if target.permission not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            f"importing {target.key} needs the {target.permission} permission",
        )


def _target_permission(key: str) -> str | None:
    """What this target needs, or `None` when the product no longer declares it.

    Separate from `_target` because a history row naming a retired target must
    still be listed: the run is the only record that the import happened, and
    raising a 404 for one row would hide every row.
    """
    try:
        return registry.require(key).permission
    except KeyError:
        return None


def _target(key: str) -> ImportTarget:
    try:
        return registry.require(key)
    except KeyError:
        # 404 rather than 422: a key nobody declared is a caller asking about
        # something this product does not offer, and the answer is the same one
        # an unknown report key gets.
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.IMPORT_TARGET_NOT_FOUND,
            f"this product accepts no import called {key}",
        ) from None


def _run_or_404(run: store.Run | None) -> store.Run:
    if run is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.IMPORT_RUN_NOT_FOUND,
            "no import run of yours has that id",
        )
    return run


# ── what a person sees ───────────────────────────────────────────────────────


class FieldView(BaseModel):
    name: str
    label_key: str
    kind: str
    required: bool
    options: list[str]


class TargetView(BaseModel):
    key: str
    label_key: str
    fields: list[FieldView]
    match_keys: list[str]
    operations: list[str]
    formats: list[str]
    max_rows: int
    #: False for a target that declares no writer. The page needs this to know
    #: whether to offer a confirm control at all -- absent rather than disabled,
    #: which is the shape Phase 1 used for the whole feature.
    committable: bool


class RunView(BaseModel):
    id: str
    target: str
    status: str
    operation: str
    columns: list[str]
    mapping: dict[str, str]
    rows_total: int
    rows_valid: int
    errors_total: int
    errors_cut: bool
    error: str | None
    requested_by: str
    #: Null until somebody confirms. The second actor.
    committed_by: str | None
    created_at: datetime
    finished_at: datetime | None


class AnalysisView(BaseModel):
    columns: list[str]
    suggested: dict[str, str]
    preview: list[dict[str, str]]
    rows_seen: int
    over_ceiling: bool
    replaced: bool


class RowErrorView(BaseModel):
    #: The table's own key, and the only correct value to send back as `after`.
    #: A caller paging on `row` walks a different scale and either stops early
    #: or repeats pages. IMP2-05 in
    #: `docs/features/data-import/phase-2-review.md`.
    cursor: int
    row: int
    column: str
    field: str
    code: str
    value: str


class NewRun(BaseModel):
    target: str
    file_id: str
    operation: str = Operation.SKIP_DUPLICATE.value


class NewMapping(BaseModel):
    #: Source column name → target field name. A field the target did not
    #: declare is refused, not dropped.
    mapping: dict[str, str] = Field(default_factory=dict)


def _view(run: store.Run) -> RunView:
    return RunView(
        id=run.id,
        target=run.target,
        status=run.status,
        operation=run.operation,
        columns=list(run.columns),
        mapping=run.mapping,
        rows_total=run.rows_total,
        rows_valid=run.rows_valid,
        errors_total=run.errors_total,
        errors_cut=run.errors_cut,
        error=run.error,
        requested_by=run.requested_by,
        committed_by=run.committed_by,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/imports/targets", response_model=list[TargetView])
async def targets(claims: AuthDep, _tenant: TenantDep) -> list[TargetView]:
    """What this product accepts, of what this caller may use.

    **Filtered rather than refused.** A caller holding `imports.manage` and not
    a particular target's own permission is entitled to import *something*, so
    403 would be wrong; what they must not see is a target they cannot use, and
    its field names with it. A picker offering a choice that is refused on the
    next request is worse than one that does not offer it. IMP2-03 in
    `docs/features/data-import/phase-2-review.md`.
    """
    _require(claims, "listing what may be imported")
    held = permissions_for(claims.roles)
    return [
        TargetView(
            key=target.key,
            label_key=target.label_key,
            fields=[
                FieldView(
                    name=spec.name,
                    label_key=spec.label_key,
                    kind=spec.kind.value,
                    required=spec.required,
                    options=list(spec.options),
                )
                for spec in target.fields
            ],
            match_keys=list(target.match_keys),
            operations=[operation.value for operation in target.operations],
            formats=[fmt.value for fmt in target.formats],
            max_rows=target.max_rows,
            committable=target.committable,
        )
        for target in registry
        if target.permission in held
    ]


@router.get("/imports", response_model=list[RunView])
async def history(
    claims: AuthDep,
    _tenant: TenantDep,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunView]:
    """This organisation's runs against the targets this caller may use.

    Filtered for the same reason as `targets` above, and it matters more here:
    a run view carries the file's own column headings and the mapping chosen
    for them, which is a description of somebody else's payroll file even
    without a single cell of it.

    A run against a target the product no longer declares is kept -- the
    history is the only record that it happened, and `_view` does not need the
    declaration to render it.
    """
    _require(claims, "reading the import history")
    held = permissions_for(claims.roles)
    return [
        _view(run)
        for run in await store.recent(session, limit=limit)
        if _target_permission(run.target) in (None, *held)
    ]


@router.post("/imports", response_model=RunView, status_code=status.HTTP_201_CREATED)
async def start(
    body: NewRun, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RunView:
    """Start a run against a file that is already uploaded and confirmed.

    The upload itself is the ordinary three-step ticket on `/files`, with the
    `imports` category — so the source inherits retention, legal hold,
    reconciliation and the quota without any of that being restated here.
    """
    _require(claims, "starting an import")
    target = _target(body.target)
    _require_target(claims, target)

    operation = body.operation
    if operation not in {op.value for op in target.operations}:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.IMPORT_OPERATION_REFUSED,
            f"{target.key} does not permit {operation}",
        )

    # Everything knowable about the file before a column is mapped: that it
    # exists, that the upload finished, that a scanner has cleared it, and that
    # it is inside the ceiling one run reads. Told now rather than after forty
    # columns have been mapped.
    try:
        await store.check_source(session, body.file_id)
    except store.SourceRefused as refused:
        raise _source_refusal(str(refused)) from refused

    run = await store.create(
        session,
        tenant_id=tenant.id,
        target=target,
        source_file_id=body.file_id,
        requested_by=require_subject(tenant),
        operation=operation,
    )
    # In the same transaction as the run: an activity row for a run that does
    # not exist, or a run with no record of having been started, are both
    # worse than either alone.
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=require_subject(tenant),
        action="import.run.started",
        target_type="import_run",
        target_id=run.id,
        outcome="ok",
        details={"target": run.target, "operation": run.operation},
    )
    await session.commit()
    return _view(run)


@router.get("/imports/{run_id}", response_model=RunView)
async def one(
    run_id: str, claims: AuthDep, _tenant: TenantDep, session: DbSession
) -> RunView:
    _require(claims, "reading an import run")
    run = _run_or_404(await store.get(session, run_id))
    # The target's own permission on every route that hands back anything the
    # target was meant to gate -- which is a run's columns and mapping as much
    # as its rows. IMP-06 fixed the three routes that resolved a target; the
    # ones that did not resolve one skipped the check by not arriving at it.
    # IMP2-03 in `docs/features/data-import/phase-2-review.md`.
    _require_target(claims, _target(run.target))
    return _view(run)


@router.get("/imports/{run_id}/analysis", response_model=AnalysisView)
async def analysis(
    run_id: str,
    claims: AuthDep,
    _tenant: TenantDep,
    session: DbSession,
    storage: StorageDep,
) -> AnalysisView:
    """What the file looks like, and a mapping to offer before anybody types.

    Reads the file and stores nothing: a person may look at a mapping, change
    their mind and look again, and none of that is a state change.
    """
    _require(claims, "reading an import file")
    run = _run_or_404(await store.get(session, run_id))
    target = _target(run.target)
    # The target's own permission here too, and not only on `start`.
    # This route answers a preview of the file's rows, so a member who may
    # import *something* but not this would otherwise read the contents of an
    # upload the target was meant to gate. IMP-06 in the review.
    _require_target(claims, target)
    raw = await _bytes(session, storage, run)
    try:
        found = store.analyse(raw, target)
    except ReadRefused as refused:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.IMPORT_FILE_UNREADABLE,
            str(refused),
        ) from refused
    return AnalysisView(
        columns=list(found.columns),
        suggested=found.suggested,
        preview=found.preview,
        rows_seen=found.rows_seen,
        over_ceiling=found.over_ceiling,
        replaced=found.replaced,
    )


@router.put("/imports/{run_id}/mapping", response_model=RunView)
async def set_mapping(
    run_id: str,
    body: NewMapping,
    claims: AuthDep,
    _tenant: TenantDep,
    session: DbSession,
    storage: StorageDep,
) -> RunView:
    """Say which column is which. Refuses a mapping the target will not take."""
    _require(claims, "mapping an import")
    run = _run_or_404(await store.get(session, run_id))
    target = _target(run.target)
    _require_target(claims, target)
    raw = await _bytes(session, storage, run)

    try:
        found = store.analyse(raw, target)
        from koras_import import resolve

        resolve(target, found.columns, body.mapping)
    except ReadRefused as refused:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.IMPORT_FILE_UNREADABLE,
            str(refused),
        ) from refused
    except MappingRefused as refused:
        # Named, because "the mapping is wrong" without saying which field is a
        # refusal a person cannot act on.
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.IMPORT_MAPPING_REFUSED,
            str(refused),
        ) from refused

    if found.over_ceiling:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.IMPORT_TOO_MANY_ROWS,
            f"this file has more than the {target.max_rows} rows {target.key} takes "
            "in one run",
        )

    await store.set_mapping(
        session,
        run,
        delimiter=found.delimiter,
        encoding=found.encoding,
        columns=found.columns,
        mapping=body.mapping,
    )
    await session.commit()
    return _view(_run_or_404(await store.get(session, run_id)))


@router.post(
    "/imports/{run_id}/validate",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate(
    run_id: str,
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
    jobs: JobsDep,
) -> RunView:
    """Check every row, in the background, writing nothing.

    **The first route in this product to enqueue work.** Everything before it
    either ran in the request or waited for a clock. A dry run over a file at
    the row ceiling is minutes of work, so it cannot be either.

    202, and the run moves to `validating` — a transient state that is a state
    rather than a flag precisely so a run left there by a crashed worker is
    visible rather than lost.
    """
    _require(claims, "validating an import")
    run = _run_or_404(await store.get(session, run_id))
    _require_target(claims, _target(run.target))

    # **Before the enqueue, not after.** This advanced the run after enqueueing
    # and did not catch the refusal, so a double-click on a run already
    # `validating` answered 500 -- having already queued a second job against a
    # run the machine had just refused to move. `cancel` has caught the same
    # exception since it was written. IMP-05 in the review.
    if not may_move(run.state, RunState.VALIDATING):
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_TRANSITIONABLE,
            f"an import run in {run.status} cannot be checked",
        )

    # Read before anything is written. An unconfigured queue records and warns
    # rather than degrading quietly, and a route that answered 202 regardless
    # would be promising work nothing will do -- which is the whole reason
    # `Enqueued` carries this.
    #
    # **No idempotency key, and that is the fix rather than an omission.** It
    # was `validate:{run_id}`, which the queue holds for as long as the job's
    # result lives -- an hour by default. Re-mapping a file after a failed dry
    # run and checking it again is the *ordinary* flow, and within that hour the
    # enqueue was silently refused while this route answered 202 and moved the
    # run to `validating`: a run waiting forever on a job that was never
    # created. The lock that matters here is the state machine above, which
    # refuses a second check of a run already `validating`. A key whose lifetime
    # outlives the state it guards turns a legitimate second attempt into a
    # silent no-op. IMP2-09 in `docs/features/data-import/phase-2-review.md`.
    queued = await jobs.enqueue(
        VALIDATE_RUN,
        tenant_id=tenant.id,
        payload={"run_id": run.id},
        actor_id=require_subject(tenant),
    )
    if queued.simulated:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.IMPORT_QUEUE_UNAVAILABLE,
            "background work is not configured, so this import cannot be checked",
        )
    if queued.duplicate:
        # Nothing was enqueued, so nothing will run. Answering 202 here is what
        # stranded runs in `validating`.
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_TRANSITIONABLE,
            "this import is already being checked",
        )

    await store.begin_validation(session, run)
    await session.commit()
    return _view(_run_or_404(await store.get(session, run_id)))


@router.post(
    "/imports/{run_id}/commit",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def commit(
    run_id: str,
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
    jobs: JobsDep,
) -> RunView:
    """Confirm a checked run, and let the worker write it.

    **The second actor.** `requested_by` started the run; `committed_by` is
    written here, by whoever confirmed. They are frequently the same person and
    the table records them separately anyway, because the fact worth keeping is
    that somebody looked at a dry run and said yes.

    A run with errors never reaches this route, and not because the route
    checks: validation lands such a run in `validation_failed`, and the state
    machine has no move from there to `commit_requested`. The 409 below is what
    a double-click gets, and what a run somebody else already committed gets.

    202 and the worker does the writing -- for the same reason the dry run does,
    and one more: the write is one transaction over a file at the row ceiling,
    which is not a thing to hold a request open for.
    """
    _require(claims, "committing an import")
    run = _run_or_404(await store.get(session, run_id))
    target = _target(run.target)
    _require_target(claims, target)

    if not target.committable:
        # A target that declares no writer can be uploaded, mapped and checked
        # and never written. Refused in the same words the page uses, rather
        # than accepted and failed a minute later by a worker: a person who
        # cannot import this should learn it before they confirm.
        await _refused(session, tenant, run, "the target accepts no writer")
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_COMMITTABLE,
            f"{target.key} can be checked but not written",
        )

    if not may_move(run.state, RunState.COMMIT_REQUESTED):
        await _refused(session, tenant, run, f"the run is in {run.status}")
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_TRANSITIONABLE,
            f"an import run in {run.status} cannot be committed",
        )

    # Recorded before the enqueue, and committed before it, so the run is in
    # `commit_requested` by the time any worker can pick the job up. The other
    # order has a window in which a worker reads a run still `validated` and
    # refuses its own job.
    await store.request_commit(session, run, by=require_subject(tenant))
    # In the same transaction as the move, so the audit row and the run's own
    # record of who confirmed it cannot disagree.
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=require_subject(tenant),
        action="import.run.committed",
        target_type="import_run",
        target_id=run.id,
        outcome="ok",
        details={"target": run.target, "operation": run.operation, "rows": run.rows_valid},
    )
    await session.commit()

    queued = await jobs.enqueue(
        COMMIT_RUN,
        tenant_id=tenant.id,
        payload={"run_id": run.id},
        actor_id=require_subject(tenant),
        # The whole point of an idempotency key here rather than on the dry run:
        # two confirmations of the same run must not write the rows twice. The
        # state machine already refuses the second request, so this is the
        # second lock rather than the first -- worth having, because the two
        # protect against different failures and the cost of being wrong is a
        # customer's records imported twice.
        idempotency_key=f"commit:{run.id}",
    )
    if queued.simulated:
        # The run is already `commit_requested` and the enqueue did nothing, so
        # say so rather than leaving a person watching a state that will never
        # change. Failed rather than reverted to `validated`: a run that was
        # confirmed *was* confirmed, and the record of who confirmed it is the
        # part worth keeping.
        fresh = _run_or_404(await store.get(session, run_id))
        await store.fail(
            session, fresh, "background work is not configured, so this import was not written"
        )
        await session.commit()
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.IMPORT_QUEUE_UNAVAILABLE,
            "background work is not configured, so this import cannot be written",
        )
    if queued.duplicate:
        # **The key stays on this route**, unlike `validate` above, because
        # re-committing a run is never legitimate: `committed` and `failed` are
        # both terminal, so a duplicate here is a second request racing the
        # first rather than an ordinary second attempt. Nothing was enqueued, so
        # the run is already in hand and 409 is the truthful answer.
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_TRANSITIONABLE,
            "this import is already being written",
        )

    return _view(_run_or_404(await store.get(session, run_id)))

async def _refused(
    session: DbSession, tenant: TenantDep, run: store.Run, why: str
) -> None:
    """Record a refused commit, and commit that record.

    Its own commit because the request is about to raise: an audit row written
    on a session that then raises is an audit row nobody keeps, and a refusal
    nobody keeps is the one class of event most worth having.
    """
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=require_subject(tenant),
        action="import.run.refused",
        target_type="import_run",
        target_id=run.id,
        outcome="denied",
        details={"target": run.target, "why": why},
    )
    await session.commit()


@router.get("/imports/{run_id}/errors", response_model=list[RowErrorView])
async def errors(
    run_id: str,
    claims: AuthDep,
    _tenant: TenantDep,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    after: int = Query(default=0, ge=0),
) -> list[RowErrorView]:
    """A page of the report, in file order.

    Every problem in every row, not the first per row: a report that stopped at
    one error per row makes fixing a file as many attempts as it has columns.
    """
    _require(claims, "reading an import report")
    run = _run_or_404(await store.get(session, run_id))
    # **The most important of the four.** This answers `problem.value`, which is
    # the cell itself, out of a file whose target may be gated behind a
    # permission this caller does not hold. Analysis refused them and this did
    # not, from the same file.
    _require_target(claims, _target(run.target))
    return [
        RowErrorView(
            cursor=reported.cursor,
            row=reported.problem.row,
            column=reported.problem.column,
            field=reported.problem.field,
            code=reported.problem.code,
            value=reported.problem.value,
        )
        for reported in await store.errors(session, run_id, limit=limit, after=after)
    ]


@router.post("/imports/{run_id}/cancel", response_model=RunView)
async def cancel(
    run_id: str, claims: AuthDep, _tenant: TenantDep, session: DbSession
) -> RunView:
    """Stop a run that has not started writing.

    The state machine refuses a cancellation of a commit in flight: that is one
    transaction, and a cancellation arriving half way would either do nothing
    or leave the run claiming something untrue about what it wrote.
    """
    _require(claims, "cancelling an import")
    run = _run_or_404(await store.get(session, run_id))
    _require_target(claims, _target(run.target))
    try:
        await store.cancel(session, run)
    except Exception as refused:  # noqa: BLE001 - TransitionRefused is a ValueError
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_NOT_TRANSITIONABLE,
            str(refused),
        ) from refused
    await session.commit()
    return _view(_run_or_404(await store.get(session, run_id)))


def _source_refusal(code: str) -> HTTPException:
    """One mapping from the store's refusal codes to answers, for both callers.

    The scan refusal is **stricter than a download**: the platform withholds an
    infected file and lets a pending one be downloaded, because a person opening
    a file they uploaded is making their own judgement. Parsing is not that —
    the product reads the bytes itself and writes rows from them.
    """
    if code == "import.source.unscanned":
        return api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.FILE_QUARANTINED,
            "this file has not been checked for malware, and an import will "
            "not read a file nobody has looked at",
        )
    if code == "import.source.missing":
        return api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.FILE_NOT_FOUND,
            "the file this import was started against is gone",
        )
    if code == "import.source.too_large":
        return api_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ApiErrorCode.IMPORT_FILE_TOO_LARGE,
            "this file is larger than one import run reads in this release",
        )
    return api_error(
        status.HTTP_409_CONFLICT,
        ApiErrorCode.IMPORT_FILE_UNREADABLE,
        "the file this import was started against could not be read",
    )


async def _bytes(session: DbSession, storage: StorageDep, run: store.Run) -> bytes:
    """The source file, or the refusal that says why not."""
    try:
        return await store.source_bytes(session, storage.store, run.source_file_id)
    except store.SourceRefused as refused:
        raise _source_refusal(str(refused)) from refused
