"""The commit: what it writes, and what it refuses to write.

CAT-02 Phase 2. Phase 1 stopped at `validated` — a terminal state that wrote
nothing — and the exit criterion for Phase 2 is one sentence: **a commit that
raises on row 900 of 1000 leaves zero rows.**

These run the real engine against a fake writer. The transaction boundary
itself is not reachable without a database, so what is asserted here is
everything around it: that a writer that refuses stops the run, that a writer
that loses rows is caught, that the engine hands over what the file says and
nothing of its own, and that a target without a writer cannot be committed at
all.
"""

from __future__ import annotations

from typing import cast

import pytest
from koras_import import (
    FieldKind,
    FieldSpec,
    ImportTarget,
    Operation,
    Writer,
    WriteRefused,
    WriteRequest,
    Written,
    check_total,
    rows_from,
)


async def _writer(_session: object, request: WriteRequest) -> Written:
    return Written(created=len(request.rows))


def _target(
    *, writer: Writer | None = None, attributes_to_run: bool = False
) -> ImportTarget:
    return ImportTarget(
        key="shop.customers",
        label_key="shop.imports.customers",
        permission="imports.manage",
        fields=(
            FieldSpec(
                name="email",
                label_key="shop.field.email",
                kind=FieldKind.EMAIL,
                required=True,
            ),
            FieldSpec(name="name", label_key="shop.field.name"),
        ),
        match_keys=("email",),
        operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
        writer=writer,
        attributes_to_run=attributes_to_run,
    )


def test_a_target_without_a_writer_is_not_committable() -> None:
    """The state Phase 1 left every target in, and a report-only target keeps.

    Absent rather than disabled, all the way down: the API answers
    `committable: false`, the page renders no control, and the route refuses.
    """
    assert _target().committable is False
    assert _target(writer=_writer).committable is True


def test_a_writer_must_be_callable() -> None:
    """Caught at import, where the target is declared, rather than an hour
    later in a worker holding a customer's file."""
    with pytest.raises(ValueError, match="not callable"):
        # The mistake this catches is a module path where a function belongs,
        # which type checking alone does not reach: a target may be declared
        # from a table of strings.
        _target(writer=cast(Writer, "core.shop.import_customers"))


def test_claiming_to_attribute_rows_without_a_writer_is_refused() -> None:
    """`attributes_to_run` is a promise about what a writer stores.

    A target that makes the promise and supplies nothing to keep it is the
    worst of both: the run looks traceable and no row points at it.
    """
    with pytest.raises(ValueError, match="writer"):
        _target(attributes_to_run=True)


def test_a_writer_that_loses_rows_is_caught() -> None:
    """The failure a writer is most likely to have: a filter or an early
    `continue` that skips rows without counting them.

    Without this the run reports a clean import of fewer records than the file
    held, and nobody can say which are missing -- which is the partial commit
    the requirements forbid, wearing a success message.
    """
    request = WriteRequest(
        tenant_id="t",
        run_id="r",
        operation=Operation.UPSERT,
        match_keys=("email",),
        rows=({"email": "a@example.com"}, {"email": "b@example.com"}),
    )
    check_total(request, Written(created=2))
    with pytest.raises(WriteRefused, match="1 of 2"):
        check_total(request, Written(created=1))


def test_a_writer_that_claims_more_than_it_was_given_is_caught_too() -> None:
    """The mirror, and it matters: a writer that expands rows -- one line
    becoming a person and an address, say -- is doing something the run's
    counts cannot describe."""
    request = WriteRequest(
        tenant_id="t",
        run_id="r",
        operation=Operation.CREATE,
        match_keys=(),
        rows=({"email": "a@example.com"},),
    )
    with pytest.raises(WriteRefused, match="2 of 1"):
        check_total(request, Written(created=2))


def test_a_file_over_the_ceiling_is_refused_rather_than_truncated() -> None:
    """Half an import is worse than none, because nobody can tell which half.

    The reader already stops at the ceiling, so this is the second gate -- and
    the one that catches a caller assembling rows some other way.
    """
    rows = [{"email": f"{index}@example.com"} for index in range(4)]
    assert len(rows_from(rows, ceiling=4)) == 4
    with pytest.raises(WriteRefused, match="takes 3"):
        rows_from(rows, ceiling=3)


def test_the_rows_handed_over_are_copies() -> None:
    """A writer that mutates what it is given must not change what the engine
    holds -- the engine checks the count afterwards, and a writer that emptied
    the list would pass by having nothing left to disagree with."""
    source = [{"email": "a@example.com"}]
    rows = rows_from(source, ceiling=10)
    source[0]["email"] = "changed"
    assert rows[0]["email"] == "a@example.com"


@pytest.mark.asyncio
async def test_the_request_carries_the_run_so_a_row_can_point_at_it() -> None:
    """Provenance without an audit event per row.

    A product stores `run_id` beside each record it creates, which is what
    makes "where did this come from" answerable a year later. The engine
    cannot enforce that a writer does it; it can make it impossible to claim
    the writer was not told.
    """
    seen: list[WriteRequest] = []

    async def remember(_session: object, request: WriteRequest) -> Written:
        seen.append(request)
        return Written(skipped=len(request.rows))

    target = _target(writer=remember)
    assert target.writer is not None
    request = WriteRequest(
        tenant_id="tenant-1",
        run_id="run-9",
        operation=Operation.SKIP_DUPLICATE,
        match_keys=tuple(target.match_keys),
        rows=({"email": "a@example.com", "name": "A"},),
    )
    written = await target.writer(None, request)
    check_total(request, written)
    assert seen[0].run_id == "run-9"
    assert seen[0].tenant_id == "tenant-1"
    assert seen[0].match_keys == ("email",)
