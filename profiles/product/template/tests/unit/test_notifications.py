"""What the notification store refuses, and what it never lets fail.

The assertions worth having here are the two asymmetries.

**It refuses a programming mistake loudly.** An unregistered kind, a blank
title or a link the caller chose are bugs at the call site, and a notification
system that quietly accepted an absolute URL would be a phishing vector wearing
the product's own branding.

**It swallows a delivery failure.** The caller is in the middle of an upload,
and the upload is the thing the customer asked for. A row that could not be
written is a log line, never an exception that reaches the route.

Getting either backwards is invisible in a happy-path test, which is why this
file is mostly refusals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from koras_api.core import notifications as store


class _Result:
    def __init__(self, rows: int = 1, scalar: int = 0) -> None:
        self._rows = rows
        self._scalar = scalar

    def scalar_one(self) -> int:
        return self._scalar

    def first(self) -> object | None:
        return object() if self._rows else None

    def all(self) -> list[object]:
        return [object() for _ in range(self._rows)]

    def __iter__(self) -> Iterator[object]:
        """`recent` iterates the result to build its rows.

        Empty, because what these tests assert about the feed is the bound the
        query is given rather than the shape of what comes back -- the latter
        is the database's answer, and a hand-made row would only prove the
        hand-made row.
        """
        return iter(())


class _Session:
    """Records what it was asked to run, and can be told to fail."""

    def __init__(self, *, failing: bool = False, scalar: int = 0) -> None:
        self.parameters: list[dict[str, Any]] = []
        self._failing = failing
        self._scalar = scalar

    async def execute(
        self, statement: object, parameters: dict[str, Any] | None = None
    ) -> _Result:
        del statement
        if self._failing:
            raise RuntimeError("the database is unreachable")
        self.parameters.append(parameters or {})
        return _Result(scalar=self._scalar)


@pytest.fixture(autouse=True)
def _own_registry() -> Iterator[None]:
    """Each test starts from a known catalogue and leaves the module's alone."""
    held = list(store.kinds)
    store.kinds.clear()
    store.kinds.add(
        store.NotificationKind(key="test.thing", summary="A thing happened.")
    )
    yield
    store.kinds.clear()
    store.kinds.extend(held)


def test_a_kind_must_be_dotted_lower_case() -> None:
    with pytest.raises(ValueError, match="dotted lower-case"):
        store.NotificationKind(key="Thing", summary="no")
    with pytest.raises(ValueError, match="dotted lower-case"):
        store.NotificationKind(key="undotted", summary="no")


def test_a_kind_registered_twice_is_refused_at_import() -> None:
    """One declaration would silently win over the other."""
    with pytest.raises(ValueError, match="registered twice"):
        store.kinds.add(store.NotificationKind(key="test.thing", summary="again"))


def test_an_unregistered_kind_raises_rather_than_defaulting() -> None:
    """Defaulting would put a raw key in front of a customer.

    The same position `koras_audit.classification_of` takes for the same
    reason: an unknown key is a mistake, and guessing hides it.
    """
    with pytest.raises(KeyError, match="never registered"):
        store.kinds.require("test.unknown")


@pytest.mark.asyncio
async def test_an_absolute_url_is_refused() -> None:
    """A notification renders as something clickable.

    A clickable thing whose destination came from a caller is a phishing vector
    wearing the product's own branding, so the refusal is here as well as in
    the column — the column cannot be bypassed, and this one names the caller.
    """
    session = _Session()
    for bad in ("https://example.invalid/x", "//example.invalid/x", "javascript:x"):
        with pytest.raises(ValueError, match="never to an address a caller chose"):
            await store.notify(
                session,  # type: ignore[arg-type]
                tenant_id="t1",
                recipients=["u1"],
                kind="test.thing",
                title="Hello",
                url=bad,
            )
    assert session.parameters == []


@pytest.mark.asyncio
async def test_a_root_relative_path_is_accepted() -> None:
    session = _Session()
    written = await store.notify(
        session,  # type: ignore[arg-type]
        tenant_id="t1",
        recipients=["u1"],
        kind="test.thing",
        title="Hello",
        url="/dashboard/files",
    )
    assert written == 1
    assert session.parameters[0]["url"] == "/dashboard/files"


@pytest.mark.asyncio
async def test_a_blank_title_is_refused() -> None:
    session = _Session()
    with pytest.raises(ValueError, match="needs a title"):
        await store.notify(
            session,  # type: ignore[arg-type]
            tenant_id="t1",
            recipients=["u1"],
            kind="test.thing",
            title="   ",
        )


@pytest.mark.asyncio
async def test_one_person_named_twice_is_told_once() -> None:
    """A caller resolving owners and permission holders separately lists the
    same person twice, and telling them twice is noise the caller should not
    have to think about."""
    session = _Session()
    written = await store.notify(
        session,  # type: ignore[arg-type]
        tenant_id="t1",
        recipients=["u1", "u2", "u1", "  ", ""],
        kind="test.thing",
        title="Hello",
    )
    assert written == 2
    assert sorted(p["user_id"] for p in session.parameters) == ["u1", "u2"]


@pytest.mark.asyncio
async def test_no_recipient_is_not_an_error() -> None:
    """A rule that resolves to nobody is a question for the caller, not a 500."""
    session = _Session()
    assert (
        await store.notify(
            session,  # type: ignore[arg-type]
            tenant_id="t1",
            recipients=[],
            kind="test.thing",
            title="Hello",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_a_broadcast_larger_than_the_ceiling_is_refused() -> None:
    """One row per recipient stops being the cheap answer somewhere, and the
    refusal is loud so the day it happens is the day it is designed for."""
    session = _Session()
    with pytest.raises(ValueError, match="over the"):
        await store.notify(
            session,  # type: ignore[arg-type]
            tenant_id="t1",
            recipients=[f"u{n}" for n in range(store.MAX_RECIPIENTS + 1)],
            kind="test.thing",
            title="Hello",
        )


@pytest.mark.asyncio
async def test_a_write_that_fails_does_not_reach_the_caller() -> None:
    """The one place this swallows, and the reason it exists as a function.

    The caller is committing an upload. A notification that could not be
    written must not cost them the upload.
    """
    session = _Session(failing=True)
    assert (
        await store.notify(
            session,  # type: ignore[arg-type]
            tenant_id="t1",
            recipients=["u1"],
            kind="test.thing",
            title="Hello",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_the_declared_severity_is_used_when_none_is_given() -> None:
    store.kinds.add(
        store.NotificationKind(
            key="test.urgent", summary="Urgent.", default_severity="warning"
        )
    )
    session = _Session()
    await store.notify(
        session,  # type: ignore[arg-type]
        tenant_id="t1",
        recipients=["u1"],
        kind="test.urgent",
        title="Hello",
    )
    assert session.parameters[0]["severity"] == "warning"

    await store.notify(
        session,  # type: ignore[arg-type]
        tenant_id="t1",
        recipients=["u1"],
        kind="test.urgent",
        title="Hello",
        severity="error",
    )
    assert session.parameters[1]["severity"] == "error"


@pytest.mark.asyncio
async def test_long_text_is_trimmed_rather_than_refused() -> None:
    """A title too long is a rendering problem, not a caller's mistake.

    Different from a blank one on purpose: nothing sensible can be shown for a
    blank title, and something sensible can always be shown for a long one.
    """
    session = _Session()
    await store.notify(
        session,  # type: ignore[arg-type]
        tenant_id="t1",
        recipients=["u1"],
        kind="test.thing",
        title="x" * 500,
        body="y" * 5000,
    )
    assert len(session.parameters[0]["title"]) == 200
    assert len(session.parameters[0]["body"]) == 2000


@pytest.mark.asyncio
async def test_the_feed_is_bounded_whatever_is_asked_for() -> None:
    """The route bounds it too. Both, because a caller that reached the store
    directly would otherwise be able to ask for the whole table."""
    session = _Session()
    await store.recent(session, limit=100_000)  # type: ignore[arg-type]
    assert session.parameters[0]["limit"] == store.MAX_PAGE
    await store.recent(session, limit=0)  # type: ignore[arg-type]
    assert session.parameters[1]["limit"] == 1


@pytest.mark.asyncio
async def test_marking_read_reports_whether_anything_changed() -> None:
    """False is how the route answers 404 for a row that belongs to somebody
    else, without ever looking at whose it is."""

    class _Nothing(_Session):
        async def execute(
            self, statement: object, parameters: dict[str, Any] | None = None
        ) -> _Result:
            await super().execute(statement, parameters)
            return _Result(rows=0)

    assert await store.mark_read(_Session(), "id") is True  # type: ignore[arg-type]
    assert await store.mark_read(_Nothing(), "id") is False  # type: ignore[arg-type]
