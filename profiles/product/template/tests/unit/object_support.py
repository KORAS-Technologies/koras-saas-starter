"""Test doubles for the scanner's object reader: a scriptable object source.

Kept under `tests/` and imported by nothing in the worker. Nothing sleeps, and
no clock is read: time is a value the test passes in.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from koras_worker.scanning import ObjectIdentity, ObjectSourceError, ScanOutcome, ScanResult

ISSUED = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
FILE = "33333333-3333-4333-8333-333333333333"
OTHER_FILE = "44444444-4444-4444-8444-444444444444"
GENERATION = "55555555-5555-4555-8555-555555555555"
#: A key the finalizer wrote: the only shape the scanner reads.
KEY = f"tenants/{TENANT}/documents/{FILE}/final/{GENERATION}/report.pdf"
STAMP = datetime(2026, 10, 4, 11, 59, 30, tzinfo=UTC)


def identity(size: int, **overrides: object) -> ObjectIdentity:
    values: dict[str, object] = {
        "size": size,
        "etag": "etag-1",
        "last_modified": STAMP,
        "version_id": None,
        "provider_sha256": None,
    }
    values.update(overrides)
    return ObjectIdentity(**values)  # type: ignore[arg-type]


class Opened:
    """An open object that serves `size` bytes without holding them."""

    def __init__(
        self,
        ident: ObjectIdentity,
        body: bytes | None,
        served: int,
        *,
        fail_after: int | None = None,
        on_read: Callable[[], None] | None = None,
    ) -> None:
        self.identity = ident
        self._body = body
        self._remaining = served
        self._offset = 0
        self._served = 0
        self._fail_after = fail_after
        self._on_read = on_read
        self.requested: list[int] = []
        self.closed = False

    def read(self, amount: int) -> bytes:
        self.requested.append(amount)
        if self._on_read is not None:
            self._on_read()
        if self._fail_after is not None and self._served >= self._fail_after:
            raise ObjectSourceError("connection reset")
        take = min(amount, self._remaining)
        if self._fail_after is not None:
            take = min(take, self._fail_after - self._served)
        self._remaining -= take
        self._served += take
        if self._body is not None:
            chunk = self._body[self._offset : self._offset + take]
            self._offset += take
            return chunk
        return b"\0" * take

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeObjectSource:
    """A source whose answers are scripted. Records every call it receives.

    `stats` is consumed one answer per `stat`; the last repeats. `served`
    overrides how many bytes the read delivers, to model an object whose bytes
    do not match its metadata.
    """

    stats: list[ObjectIdentity | None | Exception]
    body: bytes | None = None
    open_identity: ObjectIdentity | None = None
    served: int | None = None
    open_error: Exception | None = None
    fail_after: int | None = None
    on_read: Callable[[], None] | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    opened: list[Opened] = field(default_factory=list)

    def __post_init__(self) -> None:
        # What the object was when the test began, whatever `stat` is scripted to say later.
        self._initial = self.stats[0]

    def stat(self, key: str) -> ObjectIdentity | None:
        self.calls.append(("stat", key))
        step = self.stats.pop(0) if len(self.stats) > 1 else self.stats[0]
        if isinstance(step, Exception):
            raise step
        return step

    def open(self, key: str) -> Opened:
        self.calls.append(("open", key))
        if self.open_error is not None:
            raise self.open_error
        first = self._initial
        assert isinstance(first, ObjectIdentity)
        ident = self.open_identity or first
        served = ident.size if self.served is None else self.served
        opened = Opened(
            ident,
            self.body,
            served,
            fail_after=self.fail_after,
            on_read=self.on_read,
        )
        self.opened.append(opened)
        return opened

    @property
    def verbs(self) -> list[str]:
        return [verb for verb, _ in self.calls]


class FirstChunkScanner:
    """Reads one chunk and answers `OK`: a scanner that stopped consuming early."""

    async def scan(self, source: AsyncIterable[bytes]) -> ScanResult:
        async for _ in source:
            break
        return ScanResult(ScanOutcome.CANDIDATE_CLEAN)

    async def ping(self) -> bool:
        return True
