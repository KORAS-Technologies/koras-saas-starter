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

from fastapi import APIRouter, Query, status
from koras_auth import JWTClaims
from koras_auth.permissions import permissions_for
from koras_import import (
    VALIDATE_RUN,
    ImportTarget,
    MappingRefused,
    Operation,
    ReadRefused,
)
from pydantic import BaseModel, Field

from ..core import imports as store
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
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/imports/targets", response_model=list[TargetView])
async def targets(claims: AuthDep, _tenant: TenantDep) -> list[TargetView]:
    """What this product accepts. Empty in a product that declares none."""
    _require(claims, "listing what may be imported")
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
        )
        for target in registry
    ]


@router.get("/imports", response_model=list[RunView])
async def history(
    claims: AuthDep,
    _tenant: TenantDep,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunView]:
    """This organisation's runs, newest first."""
    _require(claims, "reading the import history")
    return [_view(run) for run in await store.recent(session, limit=limit)]


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

    run = await store.create(
        session,
        tenant_id=tenant.id,
        target=target,
        source_file_id=body.file_id,
        requested_by=require_subject(tenant),
        operation=operation,
    )
    await session.commit()
    return _view(run)


@router.get("/imports/{run_id}", response_model=RunView)
async def one(
    run_id: str, claims: AuthDep, _tenant: TenantDep, session: DbSession
) -> RunView:
    _require(claims, "reading an import run")
    return _view(_run_or_404(await store.get(session, run_id)))


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

    # Read before anything is written. An unconfigured queue records and warns
    # rather than degrading quietly, and a route that answered 202 regardless
    # would be promising work nothing will do -- which is the whole reason
    # `Enqueued` carries this.
    queued = await jobs.enqueue(
        VALIDATE_RUN,
        tenant_id=tenant.id,
        payload={"run_id": run.id},
        actor_id=require_subject(tenant),
        idempotency_key=f"validate:{run.id}",
    )
    if queued.simulated:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.IMPORT_QUEUE_UNAVAILABLE,
            "background work is not configured, so this import cannot be checked",
        )

    await store.begin_validation(session, run)
    await session.commit()
    return _view(_run_or_404(await store.get(session, run_id)))


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
    _run_or_404(await store.get(session, run_id))
    return [
        RowErrorView(
            row=problem.row,
            column=problem.column,
            field=problem.field,
            code=problem.code,
            value=problem.value,
        )
        for problem in await store.errors(session, run_id, limit=limit, after=after)
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


async def _bytes(session: DbSession, storage: StorageDep, run: store.Run) -> bytes:
    """The source file, or the refusal that says why not.

    The scan check is here, and it is **stricter than a download**: the platform
    withholds an infected file and lets a pending one be downloaded, because a
    person opening a file they uploaded is making their own judgement. Parsing
    is not that — the product reads the bytes itself and writes rows from them.
    """
    try:
        return await store.source_bytes(session, storage.store, run.source_file_id)
    except store.SourceRefused as refused:
        code = str(refused)
        if code == "import.source.unscanned":
            raise api_error(
                status.HTTP_409_CONFLICT,
                ApiErrorCode.FILE_QUARANTINED,
                "this file has not been checked for malware, and an import will "
                "not read a file nobody has looked at",
            ) from refused
        if code == "import.source.missing":
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.FILE_NOT_FOUND,
                "the file this import was started against is gone",
            ) from refused
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IMPORT_FILE_UNREADABLE,
            "the file this import was started against could not be read",
        ) from refused
