"""Scans a set of crafted inputs through a running clamd and prints the answers.

Run inside a container that shares clamd's network namespace, by
tests/clamd-image.test.ts:

    docker run --rm --network container:<clamd> python:3.12-slim python image_probe.py

It speaks clamd's INSTREAM protocol directly rather than using clamdscan, because
clamdscan scanned by path when this was first measured and so never exercised
StreamMaxLength at all.

Each input is built here, from nothing, so no file in the repository is itself
something an antivirus would quarantine. The marker the "hidden" cases look for
is not a real signature: the test loads a one-line custom signature for it into
the container first.
"""

import io
import json
import os
import socket
import struct
import sys
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator

MiB = 1 << 20
MARKER = b"KORAS-MARKER-0123456789"
HOST = ("::1", 3310)


def scan(data_chunks: Iterable[bytes]) -> str:
    s = socket.create_connection(HOST, timeout=600)
    s.sendall(b"zINSTREAM\0")
    try:
        for chunk in data_chunks:
            s.sendall(struct.pack("!I", len(chunk)) + chunk)
        s.sendall(struct.pack("!I", 0))
    except OSError:
        pass  # the server may refuse mid-stream; its reply is still the answer
    reply = b""
    try:
        while True:
            part = s.recv(4096)
            if not part:
                break
            reply += part
    except OSError as exc:
        reply += repr(exc).encode()
    return reply.strip(b"\0\n").decode()


def chunks(blob: bytes, size: int = MiB) -> Iterator[bytes]:
    for i in range(0, len(blob), size):
        yield blob[i : i + size]


def zipped(entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def office(parts: int, part_size: int) -> bytes:
    body = (b"<row><c>1</c></row>" * (part_size // 19 + 1))[:part_size]
    return zipped(
        [("[Content_Types].xml", b"<Types/>")]
        + [(f"xl/worksheets/sheet{i}.xml", body) for i in range(parts)]
    )


def encrypted() -> bytes:
    # The encryption flag, set on every header of an ordinary archive. clamd
    # reads the flag; it does not need a real cipher to refuse to look inside.
    d = bytearray(office(3, 1000))
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = 0
        while (i := d.find(sig, i)) >= 0:
            d[i + off] |= 1
            i += 4
    return bytes(d)


def nested(depth: int) -> bytes:
    data = b"hello"
    for i in range(depth):
        data = zipped([("inner.txt" if i == 0 else f"l{i}.zip", data)])
    return data


def streamed_zip64(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with z.open("a.bin", "w", force_zip64=True) as f:
            f.write(payload)
    return buf.getvalue()


def timed(name: str, fn: Callable[[], str]) -> tuple[str, dict[str, object]]:
    t = time.time()
    answer = fn()
    return name, {"answer": answer, "seconds": round(time.time() - t, 1)}


results = dict(
    [
        timed("ordinary", lambda: scan(chunks(office(30, 2 * MiB)))),
        timed("encrypted", lambda: scan(chunks(encrypted()))),
        timed("nested_ok", lambda: scan(chunks(nested(3)))),
        timed("nested_deep", lambda: scan(chunks(nested(12)))),
        timed("flood", lambda: scan(chunks(zipped([(f"f{i}.txt", b"x") for i in range(6000)])))),
        # Exactly the ceiling, and one byte over.
        timed("exact_ceiling", lambda: scan(chunks(os.urandom(100 * MiB)))),
        timed("over_ceiling", lambda: scan(chunks(os.urandom(100 * MiB + 1)))),
        # An entry larger than every limit: must ALERT, not scan clean.
        timed("entry_1gib", lambda: scan(chunks(zipped([("a.bin", bytes(MiB) * 1024)])))),
        # Total expansion over MaxScanSize through many entries that are each small.
        timed(
            "many_60mib",
            lambda: scan(chunks(zipped([(f"a{i}.bin", bytes(MiB) * 60) for i in range(10)]))),
        ),
        # The silent-skip window: a marker deeper than the 100 MiB ceiling, inside
        # one archive entry. With MaxFileSize at the ceiling this scanned clean.
        timed(
            "hidden_120mib", lambda: scan(chunks(zipped([("a.bin", bytes(MiB) * 120 + MARKER)])))
        ),
        timed("hidden_40mib", lambda: scan(chunks(zipped([("a.bin", bytes(MiB) * 40 + MARKER)])))),
        # KNOWN GAP in ClamAV 1.4.6 and 1.5.4: a deflated, streamed, zip64 entry
        # is not unpacked at all. A tripwire, not an endorsement -- see
        # docs/CLAMD_SERVICE.md.
        timed(
            "known_gap_zip64_streamed", lambda: scan(chunks(streamed_zip64(b"x" * 100 + MARKER)))
        ),
        timed("control_plain_zip", lambda: scan(chunks(zipped([("a.bin", b"x" * 100 + MARKER)])))),
    ]
)
json.dump(results, sys.stdout)
