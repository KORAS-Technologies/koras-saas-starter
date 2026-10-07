"""A direct client for clamd's TCP protocol: `PING` and `INSTREAM`.

The protocol is two commands and one reply line, so this is a small client and
not a dependency. It does not shell out to `clamdscan`,
holds no credential, and talks to one operator-configured address.

Commands are null-terminated (`zPING`, `zINSTREAM`) so the reply is null
terminated too and cannot be confused with a newline inside a signature name.
`INSTREAM` sends length-prefixed chunks (a 4-byte big-endian length, then the
bytes) and ends with a zero length.

**The reply is untrusted input.** It is read with a hard length bound, decoded
as ASCII, and matched against exactly the shapes clamd defines. A reply that is
none of them is `MALFORMED_RESPONSE`; the default branch of the parser is
failure, never `OK`. `OK` is the single reply that yields `CANDIDATE_CLEAN`, and
it must be exactly `stream: OK`.

**ClamAV `OK` is a candidate.** It may be returned for a streamed, deflated
ZIP64 entry that was not inspected. Nothing here, and
nothing the engine can be configured to say, makes this client report more than
a candidate.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from .protocol import Scanner
from .result import IncompleteKind, ScanOutcome, ScanResult

logger = logging.getLogger(__name__)

#: Bytes per INSTREAM chunk. Larger source blocks are split so the ceiling is
#: observed between chunks rather than after a block of arbitrary size.
CHUNK_BYTES = 64 * 1024

#: A reply longer than this without its terminator is malformed, not read on.
MAX_REPLY_BYTES = 1024

_TERMINATOR = b"\0"
_ZERO_CHUNK = b"\0\0\0\0"

# `stream: <name> FOUND`. The name is classified and discarded; the character
# class is printable ASCII without whitespace, which every ClamAV signature is.
_FOUND = re.compile(r"^stream: ([!-~]{1,256}) FOUND$")
_ERROR = re.compile(r"^[ -~]{1,200} ERROR$")
_LIMIT_ERROR = "INSTREAM size limit exceeded. ERROR"

_ENCRYPTED = "Heuristics.Encrypted."
_LIMITS = "Heuristics.Limits."
_HEURISTICS = "Heuristics."


class _SourceFailed(Exception):
    """The object source raised; carries nothing of what it said."""


class _LimitExceeded(Exception):
    """More bytes than the ceiling; the stream is abandoned unterminated."""


def parse_reply(reply: str) -> ScanResult:
    """Map one reply line to an outcome. Anything unrecognised is malformed."""
    if reply == "stream: OK":
        return ScanResult(ScanOutcome.CANDIDATE_CLEAN)
    found = _FOUND.match(reply)
    if found:
        return _classify_found(found.group(1))
    if reply == _LIMIT_ERROR:
        return ScanResult(ScanOutcome.LIMIT_EXCEEDED)
    if _ERROR.match(reply):
        return ScanResult(ScanOutcome.SCANNER_ERROR)
    return ScanResult(ScanOutcome.MALFORMED_RESPONSE)


def _classify_found(signature: str) -> ScanResult:
    """Ordinary signatures are detections; every `Heuristics.*` is a hold.

    Design decision: a heuristic result is not a malware
    verdict and not a pass. With `AlertEncrypted` and `AlertExceedsMax` on,
    clamd reports an encrypted archive or an exceeded limit as a heuristic
    `FOUND`, and other heuristic families say the engine reached a conclusion by
    inference rather than by signature. All of them leave the file `pending`:
    never quarantined on a heuristic alone, never released.

    * `Heuristics.Limits.*`: a limit was hit, `LIMIT_EXCEEDED`.
    * `Heuristics.Encrypted.*`: `INCOMPLETE_INSPECTION`, kind encrypted.
    * any other `Heuristics.*`: `INCOMPLETE_INSPECTION`, kind incomplete.
    * everything else: `INFECTED`.
    """
    if signature.startswith(_LIMITS):
        return ScanResult(ScanOutcome.LIMIT_EXCEEDED)
    if signature.startswith(_ENCRYPTED):
        return ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, IncompleteKind.ENCRYPTED)
    if signature.startswith(_HEURISTICS):
        return ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, IncompleteKind.INCOMPLETE)
    return ScanResult(ScanOutcome.INFECTED)


async def _pieces(source: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    """The source's blocks, split to `CHUNK_BYTES`; any source error is `_SourceFailed`."""
    iterator = source.__aiter__()
    while True:
        try:
            block = await iterator.__anext__()
        except StopAsyncIteration:
            return
        except Exception as exc:  # noqa: BLE001 - whatever the reader raised is a read failure
            raise _SourceFailed from exc
        for start in range(0, len(block), CHUNK_BYTES):
            yield block[start : start + CHUNK_BYTES]


@dataclass(frozen=True, slots=True)
class ClamdScanner:
    """`Scanner` over clamd's TCP port. Construct it through `resolve_scanner`."""

    host: str
    port: int
    connect_timeout: float
    scan_timeout: float
    max_bytes: int

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(self.connect_timeout):
                reader, writer = await asyncio.open_connection(
                    self.host, self.port, limit=MAX_REPLY_BYTES
                )
                try:
                    writer.write(b"zPING\0")
                    await writer.drain()
                    reply = await reader.readuntil(_TERMINATOR)
                finally:
                    _close(writer)
        except (TimeoutError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return False
        return reply == b"PONG\0"

    async def scan(self, source: AsyncIterable[bytes]) -> ScanResult:
        try:
            async with asyncio.timeout(self.scan_timeout):
                return await self._scan(source)
        except TimeoutError:
            return ScanResult(ScanOutcome.TIMEOUT)

    async def _scan(self, source: AsyncIterable[bytes]) -> ScanResult:
        try:
            async with asyncio.timeout(self.connect_timeout):
                reader, writer = await asyncio.open_connection(
                    self.host, self.port, limit=MAX_REPLY_BYTES
                )
        except (TimeoutError, OSError):
            # Refused, unresolvable, unreachable, or no answer to the SYN.
            return ScanResult(ScanOutcome.UNAVAILABLE)
        sent = 0
        try:
            try:
                writer.write(b"zINSTREAM\0")
                async for piece in _pieces(source):
                    sent += len(piece)
                    if sent > self.max_bytes:
                        raise _LimitExceeded
                    writer.write(len(piece).to_bytes(4, "big") + piece)
                    await writer.drain()
                writer.write(_ZERO_CHUNK)
                await writer.drain()
            except _SourceFailed:
                return ScanResult(ScanOutcome.READ_FAILURE, bytes_sent=sent)
            except _LimitExceeded:
                # Closed without the terminating chunk: the engine never sees a
                # complete stream, so it cannot answer OK for a truncated one.
                return ScanResult(ScanOutcome.LIMIT_EXCEEDED, bytes_sent=sent)
            except OSError:
                # The peer closed mid-stream. clamd does this after answering
                # `size limit exceeded`; the reply, if any, is read below.
                pass
            return await self._read_reply(reader, sent)
        finally:
            _close(writer)

    async def _read_reply(self, reader: asyncio.StreamReader, sent: int) -> ScanResult:
        try:
            raw = await reader.readuntil(_TERMINATOR)
        except asyncio.IncompleteReadError as exc:
            # Nothing at all is a disconnect; part of a reply is a bad reply.
            outcome = ScanOutcome.MALFORMED_RESPONSE if exc.partial else ScanOutcome.UNAVAILABLE
            return ScanResult(outcome, bytes_sent=sent)
        except asyncio.LimitOverrunError:
            return ScanResult(ScanOutcome.MALFORMED_RESPONSE, bytes_sent=sent)
        except OSError:
            return ScanResult(ScanOutcome.UNAVAILABLE, bytes_sent=sent)
        try:
            reply = raw[:-1].decode("ascii")
        except UnicodeDecodeError:
            return ScanResult(ScanOutcome.MALFORMED_RESPONSE, bytes_sent=sent)
        parsed = parse_reply(reply)
        return ScanResult(parsed.outcome, parsed.incomplete_kind, bytes_sent=sent)


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except OSError:  # pragma: no cover - a close that fails has nothing left to protect
        logger.debug("scanner connection close failed")


# Static check that the client satisfies the contract.
_: type[Scanner] = ClamdScanner
