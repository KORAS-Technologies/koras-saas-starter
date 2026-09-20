"""What the import store refuses, and the one thing it must never do.

`koras-import` has its own suite for the engine — the reader, the mapping, the
state machine. What is left for this file is the part that only exists once the
engine is wired to a database and a bucket, and three properties are worth
asserting here because each is invisible in a happy-path test.

**A dry run writes nothing of the target table.** `record_validation` lands a
run in `validated` or `validation_failed`, and every statement it issues names
`import_runs` or `import_row_errors`. A statement naming anything else would be
an import that happened without anybody confirming it.

**A refusal names both states.** Every move goes through `_advance`, which asks
the state machine first, so a caller who cancels a finished run is told rather
than issuing an `UPDATE` that matches nothing and reads as "the run vanished".

**A file nobody has scanned is not parsed.** This is stricter than a download
on purpose: a person opening their own file is making their own judgement, and
an import is the product parsing a stranger's file unattended.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from koras_api.core import imports as store
from koras_import import (
    FieldKind,
    FieldSpec,
    Format,
    ImportTarget,
    Operation,
    RowError,
    RunState,
    TransitionRefused,
    Validation,
)

CUSTOMERS = ImportTarget(
    key="shop.customers",
    label_key="imports.target.customers",
    permission="imports.manage",
    fields=(
        FieldSpec(name="name", label_key="imports.field.name", required=True),
        FieldSpec(
            name="email",
            label_key="imports.field.email",
            kind=FieldKind.EMAIL,
            required=True,
        ),
    ),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE,),
    formats=(Format.CSV,),
    max_rows=1000,
)

A_RUN = store.Run(
    id="11111111-1111-1111-1111-111111111111",
    target="shop.customers",
    status=RunState.MAPPED.value,
    format=Format.CSV.value,
    source_file_id="22222222-2222-2222-2222-222222222222",
    delimiter=",",
    encoding="utf-8",
    columns=("Name", "Email"),
    mapping={"Name": "name", "Email": "email"},
    operation=Operation.SKIP_DUPLICATE.value,
    rows_total=0,
    rows_valid=0,
    errors_total=0,
    errors_cut=False,
    error=None,
    requested_by="user-1",
    committed_by=None,
    created_at=datetime.now(UTC),
    started_at=None,
    finished_at=None,
)


#: The same run once a worker has picked it up. `record_validation` and `fail`
#: both move out of `validating`, because the machine has no edge from `mapped`
#: to either -- a dry run that never started cannot have found anything.
A_RUNNING = replace(A_RUN, status=RunState.VALIDATING.value)


class _Result:
    """Enough of a driver result for the statements this module issues."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def first(self) -> Any | None:  # noqa: ANN401 - a driver row
        return self._rows[0] if self._rows else None

    def one(self) -> Any:  # noqa: ANN401 - a driver row
        return self._rows[0]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._rows)


class _Session:
    """Records every statement, so a test can assert what was *not* touched."""

    def __init__(self, answers: list[_Result] | None = None) -> None:
        self.statements: list[str] = []
        self.parameters: list[dict[str, Any]] = []
        self._answers = answers or []

    async def execute(self, statement: Any, parameters: Any = None) -> _Result:  # noqa: ANN401
        self.statements.append(str(statement))
        self.parameters.append(dict(parameters or {}))
        return self._answers.pop(0) if self._answers else _Result()


def _sql(session: _Session) -> str:
    return " ".join(session.statements).lower()


# ── the dry run writes nothing ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_clean_dry_run_lands_validated_and_names_no_other_table() -> None:
    session = _Session()
    landed = await store.record_validation(
        session,  # type: ignore[arg-type]
        A_RUNNING,
        tenant_id="tenant-1",
        result=Validation(rows=3, valid=3, errors=(), truncated=False),
    )
    assert landed is RunState.VALIDATED

    sql = _sql(session)
    assert "import_runs" in sql
    # The whole point of the phase: no statement reaches a target table.
    assert "shop.customers" not in sql
    assert " customers " not in sql
    assert "insert into public.import_row_errors" not in sql


@pytest.mark.asyncio
async def test_a_dry_run_with_problems_lands_validation_failed_and_stores_them() -> None:
    session = _Session()
    landed = await store.record_validation(
        session,  # type: ignore[arg-type]
        A_RUNNING,
        tenant_id="tenant-1",
        result=Validation(
            rows=2,
            valid=1,
            errors=(
                RowError(
                    row=2,
                    column="Email",
                    field="email",
                    code="import.error.email",
                    value="not-an-address",
                ),
            ),
            truncated=False,
        ),
    )
    assert landed is RunState.VALIDATION_FAILED
    assert "import_row_errors" in _sql(session)
    # Still nothing of the target.
    assert "shop.customers" not in _sql(session)


@pytest.mark.asyncio
async def test_a_second_dry_run_replaces_the_first_report() -> None:
    """Two reports for one run would be two answers to one question."""
    session = _Session()
    await store.record_validation(
        session,  # type: ignore[arg-type]
        A_RUNNING,
        tenant_id="tenant-1",
        result=Validation(rows=1, valid=1, errors=(), truncated=False),
    )
    assert "delete from public.import_row_errors" in _sql(session)


@pytest.mark.asyncio
async def test_a_truncated_report_says_so() -> None:
    session = _Session()
    await store.record_validation(
        session,  # type: ignore[arg-type]
        A_RUNNING,
        tenant_id="tenant-1",
        result=Validation(rows=9, valid=0, errors=(), truncated=True),
    )
    update = next(row for row in session.parameters if "errors_cut" in row)
    assert update["errors_cut"] is True


# ── a refusal names both states ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelling_a_finished_run_is_refused_before_any_statement() -> None:
    session = _Session()
    finished = replace(A_RUN, status=RunState.COMMITTED.value)
    with pytest.raises(TransitionRefused) as refused:
        await store.cancel(session, finished)  # type: ignore[arg-type]
    assert "committed" in str(refused.value)
    # Nothing was issued: the machine answered while the caller was on the stack.
    assert session.statements == []


@pytest.mark.asyncio
async def test_validating_a_run_that_was_never_mapped_is_refused() -> None:
    session = _Session()
    fresh = replace(A_RUN, status=RunState.CREATED.value)
    with pytest.raises(TransitionRefused):
        await store.begin_validation(session, fresh)  # type: ignore[arg-type]
    assert session.statements == []


@pytest.mark.asyncio
async def test_a_failure_reason_is_cut_to_something_a_column_holds() -> None:
    session = _Session()
    await store.fail(session, A_RUNNING, "x" * 900)  # type: ignore[arg-type]
    written = next(row for row in session.parameters if "error" in row)
    assert len(written["error"]) == 400


# ── the source file ──────────────────────────────────────────────────────────


class _File:
    def __init__(self, status: str = "ready", scan_status: str = "clean") -> None:
        self.storage_key = "tenants/t/imports/f/customers.csv"
        self.size_bytes = 12
        self.status = status
        self.scan_status = scan_status
        self.name = "customers.csv"


class _Store:
    def __init__(self) -> None:
        self.read: list[str] = []

    async def get(self, key: str) -> bytes:
        self.read.append(key)
        return b"Name,Email\n"


@pytest.mark.parametrize("scan", sorted(store.UNPARSEABLE_SCANS))
@pytest.mark.asyncio
async def test_a_file_no_scanner_has_cleared_is_never_parsed(scan: str) -> None:
    session = _Session([_Result([_File(scan_status=scan)])])
    objects = _Store()
    with pytest.raises(store.SourceRefused):
        await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]
    assert objects.read == [], "the bytes were fetched before the scan was consulted"


@pytest.mark.asyncio
async def test_an_unfinished_upload_is_refused() -> None:
    session = _Session([_Result([_File(status="pending")])])
    objects = _Store()
    with pytest.raises(store.SourceRefused) as refused:
        await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]
    assert str(refused.value) == "import.source.not_ready"
    assert objects.read == []


@pytest.mark.asyncio
async def test_a_file_that_is_gone_is_refused_rather_than_read_as_empty() -> None:
    session = _Session([_Result([])])
    objects = _Store()
    with pytest.raises(store.SourceRefused) as refused:
        await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]
    assert str(refused.value) == "import.source.missing"
    assert objects.read == []


@pytest.mark.asyncio
async def test_a_clean_ready_file_is_read() -> None:
    session = _Session([_Result([_File()])])
    objects = _Store()
    raw = await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]
    assert raw.startswith(b"Name,Email")
    assert objects.read == ["tenants/t/imports/f/customers.csv"]


# ── reading, without a database or a bucket ──────────────────────────────────


def test_analysis_suggests_only_what_it_is_sure_of() -> None:
    found = store.analyse(b"Name,Email,Nickname\nAda,ada@example.com,ada\n", CUSTOMERS)
    assert found.columns == ("Name", "Email", "Nickname")
    assert found.suggested == {"Name": "name", "Email": "email"}
    assert found.preview[0]["Name"] == "Ada"
    assert found.over_ceiling is False


def test_a_file_over_the_ceiling_is_reported_rather_than_counted_exactly() -> None:
    small = replace(CUSTOMERS, max_rows=2)
    raw = b"Name,Email\n" + b"".join(
        f"P{index},p{index}@example.com\n".encode() for index in range(10)
    )
    found = store.analyse(raw, small)
    assert found.over_ceiling is True
    # Counting stops at the ceiling: the answer needed is whether, not how far.
    assert found.rows_seen <= small.max_rows + 1


def test_a_byte_no_strict_encoding_accepts_is_reported_not_hidden() -> None:
    """A lone 0x81 is invalid UTF-8 and is not a cp1252 character either.

    **This assertion was a disjunction until 2026-09-19** --
    `replaced is True or encoding != "utf-8"` -- whose second clause is true
    whenever the first is false, so it could not fail. It passed against a
    `decode()` in which `replaced` was structurally always False, which is
    IMP-03. Two assertions that can each fail, now.
    """
    found = store.analyse(b"Name,Email\n\x81dam,adam@example.com\n", CUSTOMERS)
    assert found.replaced is True
    assert found.encoding == "latin-1"


def test_a_file_a_strict_encoding_accepts_is_not_flagged() -> None:
    """The other half, without which the one above passes on a constant True."""
    found = store.analyse(b"Name,Email\nAdam,adam@example.com\n", CUSTOMERS)
    assert found.replaced is False
    assert found.encoding == "utf-8-sig"


def test_the_check_reads_every_row_and_reports_every_problem() -> None:
    raw = b"Name,Email\nAda,ada@example.com\n,nope\n"
    result = store.check(raw, CUSTOMERS, A_RUN)
    assert result.rows == 2
    assert result.valid == 1
    codes = {problem.code for problem in result.errors}
    assert "import.error.required" in codes
    assert "import.error.email" in codes


# ── what the review found ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_source_larger_than_the_ceiling_is_refused_before_it_is_fetched() -> None:
    """IMP-02. The size was selected and never read, and the ceiling it claimed
    to rely on defaults to five thousand megabytes."""
    big = _File()
    big.size_bytes = store.MAX_SOURCE_BYTES + 1
    session = _Session([_Result([big])])
    objects = _Store()
    with pytest.raises(store.SourceRefused) as refused:
        await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]
    assert str(refused.value) == "import.source.too_large"
    assert objects.read == [], "the object was fetched before its size was checked"


@pytest.mark.asyncio
async def test_a_source_at_the_ceiling_is_read() -> None:
    """The boundary, so the check cannot be off by one in the strict direction."""
    exact = _File()
    exact.size_bytes = store.MAX_SOURCE_BYTES
    session = _Session([_Result([exact])])
    objects = _Store()
    assert await store.source_bytes(session, objects, "file-1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_run_whose_file_retention_purged_answers_missing() -> None:
    """IMP-01. `source_file_id` is nullable now, because an import must not make
    a customer's file immortal. Null is a state with a sentence already."""
    session = _Session()
    with pytest.raises(store.SourceRefused) as refused:
        await store.source_bytes(session, _Store(), None)  # type: ignore[arg-type]
    assert str(refused.value) == "import.source.missing"
    assert session.statements == [], "a null id was sent to the database as a cast"
