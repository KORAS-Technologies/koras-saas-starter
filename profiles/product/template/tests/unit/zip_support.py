"""Test doubles for the structural gate: a ZIP builder that can lie.

Kept under `tests/` and imported by nothing in the worker. Python's `zipfile`
writes only well-formed archives, which is the wrong tool for proving that a
malformed one is held, so `build_zip` packs the records by hand and lets a test
state any flag, size, offset or name. `real_zip` and `streamed_zip64_deflated`
use the standard library's own writer, so the fixtures that matter most are the
form a real writer produces and not only the form this file imagines.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

MIB = 1024 * 1024


@dataclass
class Member:
    name: bytes
    #: The stored bytes: raw for method 0, already deflated for method 8.
    data: bytes = b""
    method: int = 0
    flags: int = 0
    #: Declared sizes. `None` means the length of `data` (stored) or of `raw` (deflated).
    usize: int | None = None
    csize: int | None = None
    streamed: bool = False
    local_zip64: bool = False  # a zip64 extra in the local header
    cd_zip64: bool = False  # sentinel sizes and a zip64 extra in the central directory
    local_name: bytes | None = None
    local_method: int | None = None
    local_flags: int | None = None
    cd_offset: int | None = None
    local_extra: bytes = b""
    cd_extra: bytes = b""
    crc: int = 0
    raw_len: int = field(default=-1, repr=False)

    @classmethod
    def deflated(cls, name: bytes, raw: bytes, **kwargs: object) -> Member:
        compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
        packed = compressor.compress(raw) + compressor.flush()
        return cls(
            name,
            packed,
            method=8,
            usize=len(raw),
            crc=zlib.crc32(raw),
            raw_len=len(raw),
            **kwargs,  # type: ignore[arg-type]
        )

    @classmethod
    def stored(cls, name: bytes, raw: bytes, **kwargs: object) -> Member:
        return cls(name, raw, method=0, crc=zlib.crc32(raw), **kwargs)  # type: ignore[arg-type]

    def sizes(self) -> tuple[int, int]:
        compressed = len(self.data) if self.csize is None else self.csize
        if self.usize is not None:
            uncompressed = self.usize
        else:
            uncompressed = len(self.data)
        return compressed, uncompressed


def _extra(header_id: int, payload: bytes) -> bytes:
    return struct.pack("<HH", header_id, len(payload)) + payload


def build_zip(
    members: list[Member],
    *,
    comment: bytes = b"",
    zip64_end: bool = False,
    entries_override: int | None = None,
    disk: int = 0,
    prefix: bytes = b"",
    zip64_end_bad_offset: bool = False,
) -> bytes:
    out = bytearray(prefix)
    records: list[tuple[Member, int]] = []
    for member in members:
        offset = len(out)
        compressed, uncompressed = member.sizes()
        flags = member.flags | (0x08 if member.streamed else 0)
        local_flags = flags if member.local_flags is None else member.local_flags
        method = member.method if member.local_method is None else member.local_method
        extra = member.local_extra
        if member.local_zip64:
            extra += _extra(0x0001, struct.pack("<QQ", uncompressed, compressed))
        if member.streamed:
            stated = (member.crc, 0xFFFFFFFF, 0xFFFFFFFF) if member.local_zip64 else (0, 0, 0)
        else:
            stated = (member.crc, compressed & 0xFFFFFFFF, uncompressed & 0xFFFFFFFF)
        name = member.name if member.local_name is None else member.local_name
        out += b"PK\x03\x04"
        out += struct.pack(
            "<HHHHHIIIHH",
            45 if member.local_zip64 else 20,
            local_flags,
            method,
            0,
            0x21,
            stated[0],
            stated[1],
            stated[2],
            len(name),
            len(extra),
        )
        out += name + extra + member.data
        if member.streamed:
            out += b"PK\x07\x08" + struct.pack("<I", member.crc)
            if member.local_zip64 or member.cd_zip64:
                out += struct.pack("<QQ", compressed, uncompressed)
            else:
                out += struct.pack("<II", compressed, uncompressed)
        records.append((member, offset))

    cd_start = len(out)
    for member, offset in records:
        compressed, uncompressed = member.sizes()
        flags = member.flags | (0x08 if member.streamed else 0)
        extra = member.cd_extra
        c_size, u_size = compressed & 0xFFFFFFFF, uncompressed & 0xFFFFFFFF
        if member.cd_zip64:
            c_size = u_size = 0xFFFFFFFF
            extra += _extra(0x0001, struct.pack("<QQ", uncompressed, compressed))
        at = offset if member.cd_offset is None else member.cd_offset
        out += b"PK\x01\x02"
        out += struct.pack(
            "<HHHHHHIIIHHHHHII",
            45 if member.cd_zip64 else 20,
            45 if member.cd_zip64 else 20,
            flags,
            member.method,
            0,
            0x21,
            member.crc,
            c_size,
            u_size,
            len(member.name),
            len(extra),
            0,
            0,
            0,
            0,
            at,
        )
        out += member.name + extra
    cd_size = len(out) - cd_start
    count = len(members) if entries_override is None else entries_override

    if zip64_end:
        z_start = len(out)
        out += b"PK\x06\x06" + struct.pack(
            "<QHHIIQQQQ", 44, 45, 45, 0, 0, count, count, cd_size, cd_start
        )
        out += b"PK\x06\x07" + struct.pack(
            "<IQI", 0, z_start + (1 if zip64_end_bad_offset else 0), 1
        )
        out += b"PK\x05\x06" + struct.pack(
            "<HHHHIIH", disk, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, len(comment)
        )
    else:
        out += b"PK\x05\x06" + struct.pack(
            "<HHHHIIH", disk, 0, count, count, cd_size, cd_start, len(comment)
        )
    out += comment
    return bytes(out)


# --- what the standard library's own writer produces -----------------------------------

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONTENT_TYPES = (
    b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    b'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
)


def real_zip(parts: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def real_docx() -> bytes:
    return real_zip(
        {
            "[Content_Types].xml": CONTENT_TYPES,
            "_rels/.rels": b"<Relationships/>",
            "word/document.xml": b"<w:document>" + b"hello world " * 200 + b"</w:document>",
        }
    )


def real_xlsx() -> bytes:
    return real_zip(
        {
            "[Content_Types].xml": CONTENT_TYPES,
            "_rels/.rels": b"<Relationships/>",
            "xl/workbook.xml": b"<workbook/>",
            "xl/worksheets/sheet1.xml": b"<worksheet>" + b"<row><c><v>1</v></c></row>" * 300,
        }
    )


class _Unseekable(io.RawIOBase):
    """A sink with no seek, which is what makes a real writer stream (flag bit 3)."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def writable(self) -> bool:
        return True

    def write(self, data: bytes | bytearray | memoryview) -> int:  # type: ignore[override]
        return self.buffer.write(data)

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.buffer.tell()


def streamed_zip(
    *,
    force_zip64: bool,
    compression: int = zipfile.ZIP_DEFLATED,
    payload: bytes = b"streamed payload " * 500,
) -> bytes:
    """A ZIP written to an unseekable sink, so the entries carry a data descriptor.

    With `force_zip64` this is the form ClamAV 1.4.6 and 1.5.4 may pass without
    inspecting: deflated, streamed, ZIP64. It comes from the standard library's
    writer, not from this file's builder.
    """
    sink = _Unseekable()
    with zipfile.ZipFile(sink, "w", compression) as archive:
        with archive.open("payload.txt", "w", force_zip64=force_zip64) as handle:
            handle.write(payload)
    return sink.buffer.getvalue()


def streamed_zip64_deflated() -> bytes:
    return streamed_zip(force_zip64=True)
