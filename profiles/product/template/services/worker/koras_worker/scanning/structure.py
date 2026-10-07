"""The bounded structural safety gate.

This is the third of the three things a file needs before it may be released:

    object gate PASS  +  scanner CANDIDATE_CLEAN  +  structural gate PASS

It exists because ClamAV may answer `OK` for a deflated, streamed ZIP64 entry
without inspecting its payload. That form is **held**, never called clean and
never called infected on structure alone. This module is a *safety validator*.
It is not a document parser, it extracts nothing, it writes nothing, and it
rewrites no customer file.

**One read.** The gate does not read the object. `ContainerProbe` is fed the
same 64 KiB chunks the scanner is fed, by `ObjectStream`, and keeps two bounded
things: the last `TAIL_BYTES` of the object (the ZIP end-of-central-directory
and the central directory live there) and, for every place the four-byte
local-file-header signature occurs, the first `LOCAL_CAPTURE_BYTES` bytes that
follow it. A candidate that is only a coincidence inside compressed data is
never looked at; the central directory names the offsets that matter. Memory is
bounded by those two limits, not by the object, and there is no second read.

**What it checks** (all fail closed; anything it cannot establish is a hold):

- the container is what the declared content type says it is, in both
  directions: a ZIP under a type that is not a ZIP type, and a ZIP type with no
  ZIP, are both a mismatch;
- exactly one valid end-of-central-directory, the central directory fully
  inside the tail window, no disk spanning, nothing before the first entry and
  nothing between the last entry and the directory;
- the entry count (5000), each name (1024 bytes) and the directory size are
  bounded **before** any entry is read;
- cumulative declared uncompressed size (500 MiB), each entry's declared size
  (500 MiB), and a compression ratio (100:1 for any entry of 1 MiB or more, and
  for the container as a whole);
- every entry's local header agrees with the central directory (name, method,
  encryption and streaming flags, sizes where the local header states them);
- entries whose stored extents overlap, duplicate names, and names that climb or
  are absolute, carry a drive, a backslash or a control character;
- encrypted entries (the flag bits, and AES method 99);
- the one form ClamAV is known to skip: **deflated + streamed (data descriptor)
  + ZIP64**, seen in the local header or the central directory;
- for DOCX and XLSX, the parts that make the file that format.

**What it deliberately does not do.** It does not inflate anything, so the
declared sizes are claims; ClamAV's own `MaxFileSize`/`MaxScanSize` (500 MiB,
`AlertExceedsMax yes`) measure the real ones and a hit there is already a hold.
It does not open a nested archive, and it does not hold a container because an
entry's *name* looks like one: a legitimate OOXML document may embed an Office
document (a DOCX carrying an `.xlsx`). The outer container is validated normally,
nesting depth inspected is 0, and nested content is left to the scanner's own
recursion (`MaxRecursion` 8). That ClamAV recursion could meet the ZIP64 gap
inside a nested archive that this gate never sees is a documented residual risk
(`docs/SECURE_FILES.md`), not something a filename can settle either way.

**Nothing here is a parser of document content.** No XML is read, so there is
no entity to resolve and nothing external to fetch. No macro or script is
looked at, let alone run. Names are compared as bytes and never joined to a
path; there is no filesystem call in this module, and no extraction.

Nothing here writes a row or says a file is clean. `PASS` and `NOT_REQUIRED`
are inputs to a release assessment (`release.py`), which also needs the object
gate, the scanner and the integrity gate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import StrEnum

from .result import Disposition, ScanFailure

MIB = 1024 * 1024

# --- the ratified bounds. None of these may be raised. ------

#: ClamAV `MaxFiles`.
MAX_ENTRIES = 5000
#: ClamAV `MaxScanSize` / `MaxFileSize`: the expanded budget, in total and per entry.
MAX_EXPANDED_BYTES = 500 * MIB
MAX_ENTRY_BYTES = 500 * MIB
#: ClamAV `MaxRecursion`. The structural gate itself inspects no nested archive.
MAX_RECURSION = 8
NESTED_ARCHIVE_DEPTH_INSPECTED = 0

# --- this gate's own bounds. ----------------------------------------------------------

#: The most the probe keeps from the end of an object. It must hold the
#: end-of-central-directory record, its comment, and the whole central directory.
TAIL_BYTES = 4 * MIB
#: Bytes kept after each local-file-header signature: the 30-byte header, a name
#: of at most `MAX_NAME_BYTES` and an extra field of at most `MAX_LOCAL_EXTRA_BYTES`.
MAX_NAME_BYTES = 1024
MAX_LOCAL_EXTRA_BYTES = 1024
LOCAL_CAPTURE_BYTES = 30 + MAX_NAME_BYTES + MAX_LOCAL_EXTRA_BYTES
#: Signature hits kept. A real archive has one per entry; more is not a container
#: this gate can bound.
MAX_LOCAL_CANDIDATES = 2 * MAX_ENTRIES
#: Compression-bomb ratio, applied from the size at which a ratio matters.
MAX_COMPRESSION_RATIO = 100
RATIO_FLOOR_BYTES = 1 * MIB

_EOCD_SEARCH = 22 + 65535
_LOCAL_SIG = b"PK\x03\x04"
_CENTRAL_SIG = b"PK\x01\x02"
_EOCD_SIG = b"PK\x05\x06"
_ZIP64_EOCD_SIG = b"PK\x06\x06"
_ZIP64_LOCATOR_SIG = b"PK\x06\x07"
_SPAN_SIG = b"PK\x07\x08"
_SENTINEL32 = 0xFFFFFFFF
_SENTINEL16 = 0xFFFF
_ZIP64_EXTRA = 0x0001

_FLAG_ENCRYPTED = 0x0001
_FLAG_STREAMED = 0x0008
_FLAG_STRONG = 0x0040
_FLAGS_MUST_AGREE = _FLAG_ENCRYPTED | _FLAG_STREAMED | _FLAG_STRONG
_METHOD_STORED = 0
_METHOD_DEFLATED = 8
_METHOD_AES = 99


class ProbeSealed(RuntimeError):
    """The probe was fed after it was finished, or read before."""


# --- the probe: a bounded pair of windows over the one stream -------------------------


class ContainerProbe:
    """Collects what a ZIP inspection needs from the stream the scanner already reads.

    `feed` is called with each chunk in order; `finish` ends it. Memory is at most
    `TAIL_BYTES` of tail, the candidates (at most `MAX_LOCAL_CANDIDATES` of at most
    `LOCAL_CAPTURE_BYTES`) and a window of one capture plus one chunk. Nothing is
    written anywhere and nothing is inflated.
    """

    def __init__(self, *, tail_bytes: int = TAIL_BYTES) -> None:
        if not _EOCD_SEARCH <= tail_bytes <= TAIL_BYTES:
            raise ValueError("the tail window must hold an EOCD and may not exceed the bound")
        self._tail_cap = tail_bytes
        self._tail = bytearray()
        self._head = bytearray()
        self._window = bytearray()
        self._window_base = 0
        self._locals: dict[int, bytes] = {}
        self._overflow = False
        self._total = 0
        self._sealed = False

    # -- feeding

    def feed(self, data: bytes) -> None:
        if self._sealed:
            raise ProbeSealed("the probe has been finished")
        if not data:
            return
        if len(self._head) < 8:
            self._head += data[: 8 - len(self._head)]
        self._total += len(data)
        self._tail += data
        if len(self._tail) > self._tail_cap + len(data):
            del self._tail[: len(self._tail) - self._tail_cap]
        self._collect_locals(data, final=False)

    def finish(self) -> None:
        if self._sealed:
            return
        self._collect_locals(b"", final=True)
        if len(self._tail) > self._tail_cap:
            del self._tail[: len(self._tail) - self._tail_cap]
        self._sealed = True

    def _collect_locals(self, data: bytes, *, final: bool) -> None:
        window = self._window + data
        base = self._window_base
        keep_from = max(0, len(window) - (len(_LOCAL_SIG) - 1))
        position = window.find(_LOCAL_SIG)
        while position != -1:
            available = len(window) - position
            if available < LOCAL_CAPTURE_BYTES and not final:
                keep_from = position
                break
            if len(self._locals) >= MAX_LOCAL_CANDIDATES:
                self._overflow = True
            else:
                self._locals[base + position] = bytes(
                    window[position : position + LOCAL_CAPTURE_BYTES]
                )
            position = window.find(_LOCAL_SIG, position + 1)
        if final:
            self._window = bytearray()
            return
        self._window = bytearray(window[keep_from:])
        self._window_base = base + keep_from

    # -- reading

    def _require_sealed(self) -> None:
        if not self._sealed:
            raise ProbeSealed("the probe has not been finished")

    @property
    def total_bytes(self) -> int:
        return self._total

    @property
    def head(self) -> bytes:
        return bytes(self._head)

    @property
    def tail(self) -> bytes:
        self._require_sealed()
        return bytes(self._tail)

    @property
    def tail_start(self) -> int:
        return self._total - len(self._tail)

    @property
    def local_candidates(self) -> dict[int, bytes]:
        self._require_sealed()
        return self._locals

    @property
    def candidates_overflowed(self) -> bool:
        return self._overflow


# --- the closed vocabularies ---------------------------------------------------------


class ContainerKind(StrEnum):
    """The ZIP-derived formats this gate validates. Closed; nothing else is invented."""

    ZIP = "zip"
    DOCX = "docx"
    XLSX = "xlsx"


class StructuralOutcome(StrEnum):
    """What the structural gate concluded. `PASS` and `NOT_REQUIRED` are the only passes."""

    #: A supported container, and every check passed.
    PASS = "pass"  # noqa: S105 - an outcome name, not a credential
    #: Not a ZIP-derived container, by the declared type **and** by the bytes. Explicit.
    NOT_REQUIRED = "not_required"
    MALFORMED = "malformed"
    ENCRYPTED = "encrypted"
    LIMIT_EXCEEDED = "limit_exceeded"
    #: The gate cannot establish safety: the ClamAV-gap form, an unsupported
    #: method, a nested archive.
    INCOMPLETE_INSPECTION = "incomplete_inspection"
    #: The declared type and the container disagree.
    TYPE_MISMATCH = "type_mismatch"
    #: A structure that is unsafe by itself: overlapping entries, duplicate or
    #: path-climbing names. Held; never `infected` on structure alone.
    UNSAFE_STRUCTURE = "unsafe_structure"

    @property
    def passed(self) -> bool:
        return self in {StructuralOutcome.PASS, StructuralOutcome.NOT_REQUIRED}


class StructuralReason(StrEnum):
    """Why, for a log line or a test. Never persisted: `scan_failure` is unchanged."""

    # malformed
    NO_CENTRAL_DIRECTORY = "no_central_directory"
    AMBIGUOUS_END_RECORD = "ambiguous_end_record"
    MULTI_DISK = "multi_disk"
    CENTRAL_DIRECTORY_TRUNCATED = "central_directory_truncated"
    CENTRAL_DIRECTORY_MISPLACED = "central_directory_misplaced"
    ENTRY_RECORD_INVALID = "entry_record_invalid"
    ENTRY_COUNT_MISMATCH = "entry_count_mismatch"
    EXTRA_FIELD_INVALID = "extra_field_invalid"
    LOCAL_HEADER_MISSING = "local_header_missing"
    LOCAL_HEADER_MISMATCH = "local_header_mismatch"
    DATA_BEFORE_FIRST_ENTRY = "data_before_first_entry"
    ENTRY_PAST_DIRECTORY = "entry_past_directory"
    STORED_SIZE_MISMATCH = "stored_size_mismatch"
    ZIP64_RECORD_INVALID = "zip64_record_invalid"
    # encrypted
    ENCRYPTED_ENTRY = "encrypted_entry"
    # limits
    ENTRY_COUNT = "entry_count"
    NAME_LENGTH = "name_length"
    DIRECTORY_SIZE = "directory_size"
    EXPANDED_TOTAL = "expanded_total"
    ENTRY_SIZE = "entry_size"
    COMPRESSION_RATIO = "compression_ratio"
    LOCAL_CANDIDATES = "local_candidates"
    LOCAL_HEADER_SIZE = "local_header_size"
    # incomplete
    ZIP64_STREAMED_DEFLATED = "zip64_streamed_deflated"
    UNSUPPORTED_METHOD = "unsupported_method"
    #: The object check carried no probe, so there were no bytes to inspect.
    PROBE_UNAVAILABLE = "probe_unavailable"
    # type
    NOT_A_CONTAINER = "not_a_container"
    CONTAINER_UNDER_OTHER_TYPE = "container_under_other_type"
    MISSING_REQUIRED_PART = "missing_required_part"
    # unsafe
    OVERLAPPING_ENTRIES = "overlapping_entries"
    DUPLICATE_NAME = "duplicate_name"
    UNSAFE_NAME = "unsafe_name"


@dataclass(frozen=True, slots=True)
class StructuralResult:
    """The structural gate's conclusion. Carries counts and a reason, never a name."""

    outcome: StructuralOutcome
    reason: StructuralReason | None = None
    kind: ContainerKind | None = None
    entries: int = 0
    declared_uncompressed_bytes: int = 0

    def __post_init__(self) -> None:
        if self.outcome.passed != (self.reason is None):
            raise ValueError("a reason belongs to a hold and only to a hold")
        if self.outcome is StructuralOutcome.PASS and self.kind is None:
            raise ValueError("a pass names the container it validated")
        if self.outcome is StructuralOutcome.NOT_REQUIRED and self.kind is not None:
            raise ValueError("not-required names no container")

    @property
    def passed(self) -> bool:
        return self.outcome.passed

    @property
    def failure(self) -> ScanFailure | None:
        """The existing `scan_failure` class for a hold. No new persisted reason."""
        if self.passed:
            return None
        if self.outcome is StructuralOutcome.LIMIT_EXCEEDED:
            return ScanFailure.SCAN_LIMIT_EXCEEDED
        return ScanFailure.INSPECTION_INCOMPLETE

    @property
    def disposition(self) -> Disposition | None:
        """Retrying the same bytes cannot change a structural answer."""
        return None if self.passed else Disposition.HOLD_UNINSPECTABLE


class _Hold(Exception):  # noqa: N818 - control flow inside this module only
    def __init__(self, outcome: StructuralOutcome, reason: StructuralReason) -> None:
        super().__init__(reason.value)
        self.outcome = outcome
        self.reason = reason


# --- declared types ------------------------------------------------------------------

_ZIP_TYPES = frozenset({"application/zip", "application/x-zip-compressed", "application/x-zip"})
_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: `application/octet-stream` says nothing, so it contradicts nothing: bytes that are
#: a ZIP under it are validated as a ZIP. Anything else that names a type is believed
#: to mean it.
_UNSPECIFIED_TYPES = frozenset({"application/octet-stream", "binary/octet-stream", ""})

_REQUIRED_PARTS: dict[ContainerKind, tuple[bytes, ...]] = {
    ContainerKind.ZIP: (),
    ContainerKind.DOCX: (b"[Content_Types].xml", b"word/document.xml"),
    ContainerKind.XLSX: (b"[Content_Types].xml", b"xl/workbook.xml"),
}


def _base_type(content_type: str | None) -> str:
    """The media type without parameters, lowercased. The filename is never consulted."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def declared_container(content_type: str | None) -> ContainerKind | None:
    """The container the declared type names, or `None` for a type that names none."""
    base = _base_type(content_type)
    if base in _ZIP_TYPES:
        return ContainerKind.ZIP
    if base == _DOCX_TYPE:
        return ContainerKind.DOCX
    if base == _XLSX_TYPE:
        return ContainerKind.XLSX
    return None


# --- inspection ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _EndRecord:
    absolute: int  # where the (zip64 or classic) end record begins, in the object
    entries: int
    directory_size: int
    directory_offset: int


def _u16(data: bytes, at: int) -> int:
    return int(struct.unpack_from("<H", data, at)[0])


def _u32(data: bytes, at: int) -> int:
    return int(struct.unpack_from("<I", data, at)[0])


def _u64(data: bytes, at: int) -> int:
    return int(struct.unpack_from("<Q", data, at)[0])


def _end_record_candidates(tail: bytes) -> list[int]:
    """Offsets in `tail` of every EOCD signature whose comment reaches exactly the end."""
    found: list[int] = []
    low = max(0, len(tail) - _EOCD_SEARCH)
    position = tail.rfind(_EOCD_SIG, low)
    while position != -1:
        if position + 22 <= len(tail) and position + 22 + _u16(tail, position + 20) == len(tail):
            found.append(position)
        position = tail.rfind(_EOCD_SIG, low, position)
    return found


def _parse_end_record(probe: ContainerProbe, tail: bytes, at: int) -> _EndRecord:
    """The one end-of-central-directory, with its ZIP64 form resolved. Raises `_Hold`."""
    start = probe.tail_start
    disk, cd_disk = _u16(tail, at + 4), _u16(tail, at + 6)
    on_disk, entries = _u16(tail, at + 8), _u16(tail, at + 10)
    size, offset = _u32(tail, at + 12), _u32(tail, at + 16)
    absolute = start + at

    locator = at - 20
    has_locator = locator >= 0 and tail[locator : locator + 4] == _ZIP64_LOCATOR_SIG
    sentinel = _SENTINEL16 in (on_disk, entries) or _SENTINEL32 in (size, offset)
    if sentinel and not has_locator:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ZIP64_RECORD_INVALID)

    if not has_locator:
        if disk or cd_disk or on_disk != entries:
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.MULTI_DISK)
        return _EndRecord(absolute, entries, size, offset)

    # ZIP64: the locator points at a zip64 end record that must end where the locator begins.
    z_disk, z_offset, z_disks = (
        _u32(tail, locator + 4),
        _u64(tail, locator + 8),
        _u32(tail, locator + 16),
    )
    if z_disk or z_disks != 1:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.MULTI_DISK)
    z_at = z_offset - start
    if z_at < 0 or z_at + 56 > len(tail) or tail[z_at : z_at + 4] != _ZIP64_EOCD_SIG:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ZIP64_RECORD_INVALID)
    record_size = _u64(tail, z_at + 4)
    if record_size < 44 or z_offset + 12 + record_size != start + locator:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ZIP64_RECORD_INVALID)
    z_this, z_cd = _u32(tail, z_at + 16), _u32(tail, z_at + 20)
    z_on_disk, z_entries = _u64(tail, z_at + 24), _u64(tail, z_at + 32)
    z_size, z_cd_offset = _u64(tail, z_at + 40), _u64(tail, z_at + 48)
    if z_this or z_cd or z_on_disk != z_entries:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.MULTI_DISK)
    # A field the classic record states without the sentinel must agree.
    if (
        (entries != _SENTINEL16 and entries != z_entries)
        or (size != _SENTINEL32 and size != z_size)
        or (offset != _SENTINEL32 and offset != z_cd_offset)
    ):
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ZIP64_RECORD_INVALID)
    return _EndRecord(z_offset, z_entries, z_size, z_cd_offset)


def _extra_fields(extra: bytes) -> dict[int, bytes]:
    """Split an extra field into its blocks. A malformed block is a hold; a repeat is too."""
    blocks: dict[int, bytes] = {}
    at = 0
    while at < len(extra):
        if at + 4 > len(extra):
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.EXTRA_FIELD_INVALID)
        header_id, size = _u16(extra, at), _u16(extra, at + 2)
        at += 4
        if at + size > len(extra) or header_id in blocks:
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.EXTRA_FIELD_INVALID)
        blocks[header_id] = extra[at : at + size]
        at += size
    return blocks


@dataclass(frozen=True, slots=True)
class _Entry:
    name: bytes
    flags: int
    method: int
    compressed: int
    uncompressed: int
    offset: int
    zip64: bool


_WIDTHS = {"uncompressed": 8, "compressed": 8, "offset": 8, "disk": 4}


def _parse_entry(directory: bytes, at: int) -> tuple[_Entry, int]:
    if at + 46 > len(directory) or directory[at : at + 4] != _CENTRAL_SIG:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ENTRY_RECORD_INVALID)
    flags, method = _u16(directory, at + 8), _u16(directory, at + 10)
    compressed, uncompressed = _u32(directory, at + 20), _u32(directory, at + 24)
    name_len, extra_len, comment_len = (
        _u16(directory, at + 28),
        _u16(directory, at + 30),
        _u16(directory, at + 32),
    )
    disk, offset = _u16(directory, at + 34), _u32(directory, at + 42)
    if name_len > MAX_NAME_BYTES:
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.NAME_LENGTH)
    end = at + 46 + name_len + extra_len + comment_len
    if end > len(directory):
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.CENTRAL_DIRECTORY_TRUNCATED)
    name = directory[at + 46 : at + 46 + name_len]
    extra = _extra_fields(directory[at + 46 + name_len : at + 46 + name_len + extra_len])

    zip64 = _ZIP64_EXTRA in extra
    wanted = [
        field
        for field, value in (
            ("uncompressed", uncompressed),
            ("compressed", compressed),
            ("offset", offset),
        )
        if value == _SENTINEL32
    ]
    if disk == _SENTINEL16:
        wanted.append("disk")
    if wanted:
        zip64 = True
        block = extra.get(_ZIP64_EXTRA)
        if block is None or len(block) < sum(_WIDTHS[w] for w in wanted):
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ZIP64_RECORD_INVALID)
        cursor = 0
        for field in wanted:
            width = _WIDTHS[field]
            value = int.from_bytes(block[cursor : cursor + width], "little")
            cursor += width
            if field == "uncompressed":
                uncompressed = value
            elif field == "compressed":
                compressed = value
            elif field == "offset":
                offset = value
            elif value:
                raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.MULTI_DISK)
    elif disk:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.MULTI_DISK)

    return _Entry(name, flags, method, compressed, uncompressed, offset, zip64), end


def _check_name(name: bytes) -> None:
    """Names that are unsafe on their own. Bytes are examined; nothing is joined to a path."""
    if (
        not name
        or name.startswith((b"/", b"\\"))
        or b"\\" in name
        or any(c < 0x20 or c == 0x7F for c in name)
        or (len(name) > 1 and name[1:2] == b":" and name[:1].isalpha())
        or any(part == b".." for part in name.split(b"/"))
    ):
        raise _Hold(StructuralOutcome.UNSAFE_STRUCTURE, StructuralReason.UNSAFE_NAME)


def _check_local(probe: ContainerProbe, entry: _Entry) -> tuple[bool, int]:
    """Compare an entry's local header with its directory record.

    Returns whether the local header carries ZIP64 evidence, and where the entry's
    stored data begins. Raises `_Hold` for any disagreement.
    """
    header = probe.local_candidates.get(entry.offset)
    if header is None:
        if probe.candidates_overflowed:
            raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.LOCAL_CANDIDATES)
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.LOCAL_HEADER_MISSING)
    if len(header) < 30:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.LOCAL_HEADER_MISMATCH)
    flags, method = _u16(header, 6), _u16(header, 8)
    stated_compressed, stated_uncompressed = _u32(header, 18), _u32(header, 22)
    name_len, extra_len = _u16(header, 26), _u16(header, 28)
    if name_len > MAX_NAME_BYTES or extra_len > MAX_LOCAL_EXTRA_BYTES:
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.LOCAL_HEADER_SIZE)
    if len(header) < 30 + name_len + extra_len:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.LOCAL_HEADER_MISMATCH)
    name = header[30 : 30 + name_len]
    extra = _extra_fields(header[30 + name_len : 30 + name_len + extra_len])
    if (
        name != entry.name
        or method != entry.method
        or (flags & _FLAGS_MUST_AGREE) != (entry.flags & _FLAGS_MUST_AGREE)
    ):
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.LOCAL_HEADER_MISMATCH)

    zip64 = _ZIP64_EXTRA in extra or _SENTINEL32 in (stated_compressed, stated_uncompressed)
    # Where the local header states sizes (not streamed, not ZIP64) it must agree.
    if (
        not (flags & _FLAG_STREAMED)
        and not zip64
        and (stated_compressed != entry.compressed or stated_uncompressed != entry.uncompressed)
    ):
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.LOCAL_HEADER_MISMATCH)
    return zip64, entry.offset + 30 + name_len + extra_len


def _inspect_zip(probe: ContainerProbe, kind: ContainerKind) -> StructuralResult:
    tail = probe.tail
    candidates = _end_record_candidates(tail)
    if not candidates:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.NO_CENTRAL_DIRECTORY)
    if len(candidates) > 1:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.AMBIGUOUS_END_RECORD)
    end = _parse_end_record(probe, tail, candidates[0])

    # Bound everything declared before anything declared is read.
    if end.entries > MAX_ENTRIES:
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.ENTRY_COUNT)
    if end.directory_offset + end.directory_size != end.absolute:
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.CENTRAL_DIRECTORY_MISPLACED)
    if end.directory_offset < probe.tail_start:
        # Correctly placed, but longer than the window this gate holds.
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.DIRECTORY_SIZE)
    if probe.candidates_overflowed:
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.LOCAL_CANDIDATES)

    base = end.directory_offset - probe.tail_start
    directory = tail[base : base + end.directory_size]

    entries: list[_Entry] = []
    at = 0
    for _ in range(end.entries):
        entry, at = _parse_entry(directory, at)
        entries.append(entry)
    if at != len(directory):
        raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ENTRY_COUNT_MISMATCH)

    # Encryption outranks every other finding on an entry, and on the archive.
    if any(e.flags & (_FLAG_ENCRYPTED | _FLAG_STRONG) or e.method == _METHOD_AES for e in entries):
        raise _Hold(StructuralOutcome.ENCRYPTED, StructuralReason.ENCRYPTED_ENTRY)

    total = 0
    names: set[bytes] = set()
    extents: list[tuple[int, int]] = []
    for entry in entries:
        _check_name(entry.name)
        if entry.name in names:
            raise _Hold(StructuralOutcome.UNSAFE_STRUCTURE, StructuralReason.DUPLICATE_NAME)
        names.add(entry.name)

        if entry.method not in {_METHOD_STORED, _METHOD_DEFLATED}:
            raise _Hold(
                StructuralOutcome.INCOMPLETE_INSPECTION, StructuralReason.UNSUPPORTED_METHOD
            )
        if entry.method == _METHOD_STORED and entry.compressed != entry.uncompressed:
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.STORED_SIZE_MISMATCH)

        local_zip64, data_start = _check_local(probe, entry)
        streamed = bool(entry.flags & _FLAG_STREAMED)
        # The form ClamAV may pass without inspecting: deflated + streamed + ZIP64.
        # Either header showing ZIP64 is enough: a writer may state it in only one.
        if entry.method == _METHOD_DEFLATED and streamed and (entry.zip64 or local_zip64):
            raise _Hold(
                StructuralOutcome.INCOMPLETE_INSPECTION,
                StructuralReason.ZIP64_STREAMED_DEFLATED,
            )

        if entry.uncompressed > MAX_ENTRY_BYTES:
            raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.ENTRY_SIZE)
        total += entry.uncompressed
        if total > MAX_EXPANDED_BYTES:
            raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.EXPANDED_TOTAL)
        if (
            entry.uncompressed >= RATIO_FLOOR_BYTES
            and entry.uncompressed > entry.compressed * MAX_COMPRESSION_RATIO
        ):
            raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.COMPRESSION_RATIO)

        data_end = data_start + entry.compressed
        if data_end > end.directory_offset:
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.ENTRY_PAST_DIRECTORY)
        extents.append((entry.offset, data_end))

    if total >= RATIO_FLOOR_BYTES and total > probe.total_bytes * MAX_COMPRESSION_RATIO:
        raise _Hold(StructuralOutcome.LIMIT_EXCEEDED, StructuralReason.COMPRESSION_RATIO)

    extents.sort()
    if extents:
        if extents[0][0] != 0:
            raise _Hold(StructuralOutcome.MALFORMED, StructuralReason.DATA_BEFORE_FIRST_ENTRY)
        for (_, ends), (next_start, _) in zip(extents, extents[1:], strict=False):
            if next_start < ends:
                raise _Hold(
                    StructuralOutcome.UNSAFE_STRUCTURE, StructuralReason.OVERLAPPING_ENTRIES
                )

    for part in _REQUIRED_PARTS[kind]:
        if part not in names:
            raise _Hold(StructuralOutcome.TYPE_MISMATCH, StructuralReason.MISSING_REQUIRED_PART)

    return StructuralResult(
        StructuralOutcome.PASS, kind=kind, entries=len(entries), declared_uncompressed_bytes=total
    )


def _looks_like_zip(probe: ContainerProbe) -> bool:
    """Whether bytes declared as something else are in fact a ZIP, by signature or end record."""
    if probe.head[:4] in {_LOCAL_SIG, _EOCD_SIG, _SPAN_SIG}:
        return True
    tail = probe.tail
    for at in _end_record_candidates(tail):
        size, offset = _u32(tail, at + 12), _u32(tail, at + 16)
        has_locator = at >= 20 and tail[at - 20 : at - 16] == _ZIP64_LOCATOR_SIG
        if has_locator or _SENTINEL32 in (size, offset):
            return True
        if offset + size == probe.tail_start + at:
            return True
        # Bytes in front of the archive shift every offset, so the end record's own
        # arithmetic is not evidence either way; a central directory header exactly
        # where its size says it begins is.
        if 0 < size <= at and tail[at - size : at - size + 4] == _CENTRAL_SIG:
            return True
    return False


def inspect_container(probe: ContainerProbe, content_type: str | None) -> StructuralResult:
    """Run the structural gate over a probe and the file's declared type.

    The declared type is the row's `content_type`. The filename is not an input.
    Always returns a result: an unexpected shape of input is a hold, never a pass.

    | declared type | bytes | result |
    |---|---|---|
    | ZIP / DOCX / XLSX | a container | the checks above; `PASS` or a hold |
    | ZIP / DOCX / XLSX | not a container | `TYPE_MISMATCH` |
    | `application/octet-stream`, none | a container | checked as a ZIP |
    | `application/octet-stream`, none | not a container | `NOT_REQUIRED` |
    | any other type | a container | `TYPE_MISMATCH` |
    | any other type | not a container | `NOT_REQUIRED` |
    """
    try:
        probe.finish()
        kind = declared_container(content_type)
        is_container = _looks_like_zip(probe)
        if kind is not None:
            if not is_container:
                raise _Hold(StructuralOutcome.TYPE_MISMATCH, StructuralReason.NOT_A_CONTAINER)
            return _inspect_zip(probe, kind)
        if not is_container:
            return StructuralResult(StructuralOutcome.NOT_REQUIRED)
        if _base_type(content_type) in _UNSPECIFIED_TYPES:
            return _inspect_zip(probe, ContainerKind.ZIP)
        raise _Hold(StructuralOutcome.TYPE_MISMATCH, StructuralReason.CONTAINER_UNDER_OTHER_TYPE)
    except _Hold as hold:
        return StructuralResult(hold.outcome, hold.reason)
    except (struct.error, ValueError, IndexError, OverflowError):
        # A shape this module did not foresee is not a pass.
        return StructuralResult(StructuralOutcome.MALFORMED, StructuralReason.ENTRY_RECORD_INVALID)
