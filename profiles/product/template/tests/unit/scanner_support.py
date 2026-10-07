"""Test doubles for the scanner foundation: a fake scanner and a fake clamd.

Kept under `tests/` and imported by nothing in the worker. The production
package has no fake and no bypass; `resolve_scanner` cannot return either of
these, and `test_scanner_foundation.py` asserts it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from koras_worker.scanning import ScanOutcome, ScanResult
from koras_worker.scanning.protocol import ObjectReadError


async def blocks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def failing_source() -> AsyncIterator[bytes]:
    yield b"first"
    raise ObjectReadError("storage said no")


class FakeScanner:
    """A deterministic `Scanner`: returns a scripted result after draining the source."""

    def __init__(self, result: ScanResult) -> None:
        self._result = result
        self.received = 0
        self.pings = 0

    @classmethod
    def candidate_clean(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.CANDIDATE_CLEAN))

    @classmethod
    def infected(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.INFECTED))

    @classmethod
    def timeout(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.TIMEOUT))

    @classmethod
    def unavailable(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.UNAVAILABLE))

    @classmethod
    def malformed(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.MALFORMED_RESPONSE))

    @classmethod
    def limit_exceeded(cls) -> FakeScanner:
        return cls(ScanResult(ScanOutcome.LIMIT_EXCEEDED))

    async def scan(self, source: AsyncIterable[bytes]) -> ScanResult:
        try:
            async for block in source:
                self.received += len(block)
        except Exception:  # noqa: BLE001 - a failing source is a read failure, as in the real client
            return ScanResult(ScanOutcome.READ_FAILURE, bytes_sent=self.received)
        return self._result

    async def ping(self) -> bool:
        self.pings += 1
        return self._result.outcome is not ScanOutcome.UNAVAILABLE


Behaviour = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


@dataclass
class FakeClamd:
    """A TCP server speaking just enough of clamd's protocol, scripted per test."""

    host: str = "127.0.0.1"
    port: int = 0
    commands: list[bytes] = field(default_factory=list)
    streamed: bytearray = field(default_factory=bytearray)
    terminated: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def read_stream(
        self, reader: asyncio.StreamReader, stop_after: int | None = None
    ) -> None:
        """Consume INSTREAM chunks until the zero chunk, or until `stop_after` bytes."""
        while True:
            header = await reader.readexactly(4)
            size = int.from_bytes(header, "big")
            if size == 0:
                self.terminated = True
                return
            self.streamed += await reader.readexactly(size)
            if stop_after is not None and len(self.streamed) >= stop_after:
                return


def replying(fake: FakeClamd, reply: bytes) -> Behaviour:
    """Read the whole stream, then send `reply` verbatim and close."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fake.commands.append(await reader.readuntil(b"\0"))
        if fake.commands[-1] == b"zPING\0":
            writer.write(reply)
        else:
            await fake.read_stream(reader)
            writer.write(reply)
        await writer.drain()

    return handle


def replying_early(fake: FakeClamd, reply: bytes, after: int) -> Behaviour:
    """Answer and hang up after `after` streamed bytes, as clamd does at its limit."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fake.commands.append(await reader.readuntil(b"\0"))
        await fake.read_stream(reader, stop_after=after)
        writer.write(reply)
        await writer.drain()

    return handle


def hanging(fake: FakeClamd) -> Behaviour:
    """Accept, read the command, and never answer."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fake.commands.append(await reader.readuntil(b"\0"))
        await fake.release.wait()

    return handle


def hanging_up(fake: FakeClamd) -> Behaviour:
    """Read the whole stream, then close without a byte of reply."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fake.commands.append(await reader.readuntil(b"\0"))
        await fake.read_stream(reader)

    return handle


def dropping(fake: FakeClamd, after: int) -> Behaviour:
    """Close the connection abruptly once `after` bytes have arrived."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fake.commands.append(await reader.readuntil(b"\0"))
        await fake.read_stream(reader, stop_after=after)
        writer.transport.abort()

    return handle


@asynccontextmanager
async def serving(
    make: Callable[[FakeClamd], Behaviour],
) -> AsyncIterator[FakeClamd]:
    fake = FakeClamd()
    behaviour = make(fake)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await behaviour(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handler, fake.host, 0)
    fake.port = server.sockets[0].getsockname()[1]
    try:
        yield fake
    finally:
        fake.release.set()
        server.close()
        await server.wait_closed()


async def closed_port() -> int:
    """A port that was just free and has nothing listening: connection refused."""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port
