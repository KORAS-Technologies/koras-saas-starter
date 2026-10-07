"""The scanner contract. A vendor adapter implements this and changes nothing else."""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Protocol, runtime_checkable

from .result import ScanResult


class ObjectReadError(Exception):
    """Raised by an object source when the bytes could not be read.

    A scanner maps it, and any other exception the source raises, to
    `READ_FAILURE`: a source that fails is the reader's fault, not a verdict
    on the object and not an outage of the scanner.
    """


@runtime_checkable
class Scanner(Protocol):
    """Streams an object's bytes to an engine and reports what it concluded.

    `scan` never raises for an operational failure and never returns anything
    that reads as a pass unless the engine said so: every failure is a
    `ScanResult` with a hold outcome. The scanner is handed bytes and no tenant
    identity, no signed URL and no token, and keeps nothing.
    """

    async def scan(self, source: AsyncIterable[bytes]) -> ScanResult: ...

    async def ping(self) -> bool:
        """Whether the engine answered a liveness probe. Never raises."""
        ...
