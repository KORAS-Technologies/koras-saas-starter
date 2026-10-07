"""A bounded, identity-checked reader for the scanner's input.

This is the **object gate**, the first of the three things (ADR 0013, `docs/SECURE_FILES.md`)
required before a file may become releasable:

    object gate PASS  +  scanner CANDIDATE_CLEAN  +  structural gate PASS

This module is the first and nothing else. Nothing here marks a file anything: the
module has no verdict, writes no row and cannot say a file is releasable. Its
only positive answer, `ObjectGate.READY`, means "the bytes the scanner saw were
read inside the rules"; it composes with a scanner result in `release.assess_release`.

**What the gate checks, in order.**

1. *The upload window.* The signed PUT that wrote the object is valid for
   `UPLOAD_URL_SECONDS`. Until that, plus a 60 second margin, has passed since
   the ticket was issued, the bytes can still be replaced, so nothing is read:
   not even metadata. The gate is evaluated against the file row's persisted
   `created_at` and an injected clock, never a clock of its own.
2. *Existence and identity before the read.* The object's size, ETag, version,
   last-modified and provider SHA-256 (where one exists) are captured.
3. *The ceiling.* An object over `max_bytes` (100 MiB by default and never more: the
   ceiling clamd is configured for) is refused from its declared size, and a stream that outruns the
   ceiling is cut off. At most `max_bytes + 1` bytes are ever requested.
4. *The read itself.* Streamed in small chunks. As each chunk passes it is also
   hashed (SHA-256) and offered to the structural probe, so one read serves
   the scanner, the digest and the structural gate; memory is one chunk plus the
   probe's fixed bounds (`structure.py`), never the object. The
   response the provider sends for the read must describe the object that was
   inspected beforehand, and the bytes delivered must equal its size.
5. *Identity after the read.* The metadata is read again. Any difference is a
   changed object, and a changed object is never releasable.

**An ETag is identity and concurrency evidence. It is not a content digest.**
For a multipart or encrypted object it is not a hash of the bytes at all, and
for a single-part one it is an MD5. It is only ever compared with itself. The
one content digest this module can carry is the provider's own SHA-256, taken
from the checksum header the provider computed, and it is a separate field that
an ETag can never populate.

**There is no way to point this at an address.** An `ObjectReference` is a
tenant, a file and a key, validated to belong together; it has no URL, host or
bucket. The storage behind it is chosen by the caller from the product's own
settings. Nothing here signs a URL, holds a credential or reaches the network
except through the injected `ObjectSource`.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import ModuleType
from typing import Protocol

from .config import MAX_SCAN_BYTES
from .protocol import ObjectReadError
from .result import ScanFailure
from .structure import ContainerProbe

#: Memory held while streaming: one chunk. Small enough that a burst of
#: concurrent scans is not a memory event on a 512 MiB worker.
DEFAULT_CHUNK_BYTES = 64 * 1024


class ObjectGate(StrEnum):
    """What the object gate concluded. The only positive answer is `READY`.

    Every other value is a hold. None of them is a verdict about the file: they
    never mean clean, infected or skipped.
    """

    #: The object may be (or has been) consumed by the scanner and its identity held.
    READY = "ready"
    #: The upload ticket may still be live. Nothing was read.
    WINDOW_NOT_ELAPSED = "window_not_elapsed"
    #: The store answered and the object is not there.
    MISSING = "missing"
    #: The store could not be asked, or failed while being read.
    UNREACHABLE = "unreachable"
    #: The object is larger than the scanner's ceiling.
    OVERSIZED = "oversized"
    #: The object is not the one that was inspected, or not the one recorded.
    CHANGED = "changed"
    #: The store gave too little to tell one object from another (no ETag,
    #: version or provider digest), so safety cannot be established.
    IDENTITY_INSUFFICIENT = "identity_insufficient"
    #: The stream ended before the whole object was read.
    READ_INCOMPLETE = "read_incomplete"

    @property
    def passed(self) -> bool:
        return self is ObjectGate.READY

    @property
    def failure(self) -> ScanFailure | None:
        """The `scan_failure` class a later slice persists, or `None`.

        `None` for `READY`, and for `WINDOW_NOT_ELAPSED`, which is a deferral
        and not a failure.
        """
        return _FAILURE.get(self)

    @property
    def counts_attempt(self) -> bool:
        """Whether a later slice counts this as a scan attempt.

        A deferral reads nothing and counts nothing. An oversized object is
        held without an attempt, because retrying cannot change the answer
       . Everything else tried to read the object.
        """
        return self not in {ObjectGate.WINDOW_NOT_ELAPSED, ObjectGate.OVERSIZED}


_FAILURE: dict[ObjectGate, ScanFailure] = {
    ObjectGate.MISSING: ScanFailure.OBJECT_UNREACHABLE,
    ObjectGate.UNREACHABLE: ScanFailure.OBJECT_UNREACHABLE,
    ObjectGate.READ_INCOMPLETE: ScanFailure.OBJECT_UNREACHABLE,
    ObjectGate.OVERSIZED: ScanFailure.OVER_CEILING,
    ObjectGate.CHANGED: ScanFailure.OBJECT_CHANGED,
    ObjectGate.IDENTITY_INSUFFICIENT: ScanFailure.IDENTITY_INSUFFICIENT,
}


# --- the reference: tenant, file and key, and nothing a caller can aim ------------


class ObjectReferenceError(ValueError):
    """The tenant, file and key do not belong together, or the key is not a key."""


_SEGMENT = re.compile(r"^[A-Za-z0-9._ -]+$")


def _canonical_uuid(value: str, what: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ObjectReferenceError(f"{what} is not a UUID") from error
    if str(parsed) != value:
        raise ObjectReferenceError(f"{what} is not in canonical form")
    return value


@dataclass(frozen=True, slots=True)
class ObjectReference:
    """One object, named by the tenant and file that own it and its storage key.

    Construction is the validation: the key must be exactly the shape the upload
    route writes, under this tenant's prefix, with this file's id as one of its
    directory segments. A key that is a URL, a path that climbs, or another
    tenant's object does not construct. There is no field for a host, a scheme,
    a bucket or a credential, so there is nothing for a caller to supply.
    """

    tenant_id: str
    file_id: str
    key: str

    def __post_init__(self) -> None:
        _canonical_uuid(self.tenant_id, "tenant_id")
        _canonical_uuid(self.file_id, "file_id")
        key = self.key
        if not isinstance(key, str) or not key or len(key) > 1024:
            raise ObjectReferenceError("the storage key is empty or too long")
        if "://" in key or key.startswith(("/", "\\")) or "\\" in key:
            raise ObjectReferenceError("the storage key is not a bucket key")
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in key):
            raise ObjectReferenceError("the storage key holds a control character")
        segments = key.split("/")
        if any(not s or s in {".", ".."} or not _SEGMENT.match(s) for s in segments):
            raise ObjectReferenceError("the storage key has an unsafe segment")
        if len(segments) < 4 or segments[0] != "tenants":
            raise ObjectReferenceError("the storage key is not under tenants/<tenant>/")
        if segments[1] != self.tenant_id:
            raise ObjectReferenceError("the storage key belongs to another tenant")
        if self.file_id not in segments[2:-1]:
            raise ObjectReferenceError("the storage key does not belong to this file")


# --- identity ----------------------------------------------------------------------


def _unquote_etag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().removeprefix("W/").strip('"') or None


def _to_seconds(value: datetime | None) -> datetime | None:
    """Last-modified at the precision HTTP carries it, in UTC.

    The exact comparison is made to the second: comparing finer than that would
    call an unchanged object changed. (HEAD and GET were seen to differ by a whole
    second on a real store; that case uses `last_modified_exact`, below.)
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


#: The most the `LastModified` of a metadata request and of a read of the same object
#: may differ. Applies only to that comparison (`ObjectStream` opening the object); the
#: check after the read compares metadata with metadata and stays exact.
OPEN_LAST_MODIFIED_TOLERANCE = timedelta(seconds=1)


def _same_instant(a: ObjectIdentity, b: ObjectIdentity, tolerance: timedelta) -> bool:
    """Equal within `tolerance`; a timestamp present on one side only is a difference.

    With no tolerance the comparison is on the second-truncated value, as before.
    With one, it is on the **un-truncated** instants, so "at most one second" means
    one second of real drift: truncating first would let 5.0 and 6.999 through.
    """
    if a.last_modified is None or b.last_modified is None:
        return a.last_modified is b.last_modified
    if not tolerance:
        return a.last_modified == b.last_modified
    if a.last_modified_exact is None or b.last_modified_exact is None:
        return False
    return abs(a.last_modified_exact - b.last_modified_exact) <= tolerance


@dataclass(frozen=True, slots=True)
class ObjectIdentity:
    """What a store says about one object, kept as four distinct kinds of evidence.

    - `size`: bytes.
    - `etag`: **opaque object identity**, unquoted. Not a digest of anything.
    - `version_id` and `last_modified`: the provider's version and timestamp,
      where it supplies them.
    - `provider_sha256`: the **only** content digest here, hex, present only when
      the provider computed and returned a full SHA-256 for the stored bytes. It
      is never derived from the ETag, and an ETag that looks like a hash does not
      populate it.
    """

    size: int
    etag: str | None = None
    last_modified: datetime | None = None
    version_id: str | None = None
    provider_sha256: str | None = None
    #: `last_modified` before truncation, UTC. Used only by the one-second tolerance;
    #: not part of equality or the repr.
    last_modified_exact: datetime | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("an object cannot have a negative size")
        if self.last_modified is not None:
            exact = self.last_modified
            if exact.tzinfo is None:
                exact = exact.replace(tzinfo=UTC)
            object.__setattr__(self, "last_modified_exact", exact.astimezone(UTC))
        object.__setattr__(self, "etag", _unquote_etag(self.etag))
        object.__setattr__(self, "last_modified", _to_seconds(self.last_modified))
        object.__setattr__(self, "version_id", self.version_id or None)

    @property
    def sufficient(self) -> bool:
        """Whether this can tell this object from a replacement of the same length.

        Size and a timestamp alone cannot: a same-length overwrite inside a
        second changes neither. An ETag, a version or a provider digest can.
        """
        return bool(self.etag or self.version_id or self.provider_sha256)

    def same_object(
        self,
        other: ObjectIdentity,
        *,
        compare_digest: bool = True,
        last_modified_tolerance: timedelta = timedelta(0),
    ) -> bool:
        """True only when no recorded evidence differs. Fails closed on any difference.

        A field that is present on one side and absent on the other is a
        difference. `compare_digest=False` is for comparing a metadata request
        with the headers of a read, which may not carry the checksum.

        `last_modified_tolerance` loosens the timestamp and nothing else: size,
        ETag, version and the provider digest stay exact. It exists for the one
        comparison of a metadata request with a read, because a real store was
        seen rendering the same object's `LastModified` one second apart on
        HEAD and GET. It cannot exceed `OPEN_LAST_MODIFIED_TOLERANCE` and is measured
        on the un-truncated instants, so it is one real second, not two.
        """
        if not timedelta(0) <= last_modified_tolerance <= OPEN_LAST_MODIFIED_TOLERANCE:
            raise ValueError("the last-modified tolerance is between zero and one second")
        same = (
            self.size == other.size
            and self.etag == other.etag
            and _same_instant(self, other, last_modified_tolerance)
            and self.version_id == other.version_id
        )
        if compare_digest:
            same = same and self.provider_sha256 == other.provider_sha256
        elif self.provider_sha256 and other.provider_sha256:
            same = same and self.provider_sha256 == other.provider_sha256
        return same


# --- the source: the one place that touches storage -----------------------------


class ObjectSourceError(ObjectReadError):
    """The store could not be asked or failed mid-read. Never a verdict."""


class OpenedObject(Protocol):
    """An object open for reading, with the identity the provider sent with it."""

    identity: ObjectIdentity

    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class ObjectSource(Protocol):
    """Synchronous access to one bucket, by key only.

    Methods block; the reader runs them in a worker thread. Implementations
    take a key and nothing else: no URL, host or bucket per call, and they never
    mutate the object.
    """

    def stat(self, key: str) -> ObjectIdentity | None:
        """The object's identity, or `None` when it is not there.

        Raises `ObjectSourceError` when the store could not answer.
        """
        ...

    def open(self, key: str) -> OpenedObject:
        """Open the object for reading. Raises `ObjectSourceError` on any failure,
        including the object having disappeared since `stat`."""
        ...


# --- the window ------------------------------------------------------------------


def _upload_window() -> ModuleType:
    """The API's shared upload-window module, by name.

    Not a plain import: the worker does not depend on the API's distribution,
    and its declared-dependency test rightly refuses one. The image carries this
    one stdlib-only file (see the Dockerfile), the same arrangement as the
    import run store. **When it is missing the gate cannot be evaluated, and an
    unevaluable gate must read nothing**, so this raises rather than guessing a
    window.
    """
    try:
        return importlib.import_module("koras_api.core.upload_window")
    except ImportError as error:
        raise UploadWindowUnavailable(
            "the shared upload-window constants are not on this worker's path"
        ) from error


class UploadWindowUnavailable(RuntimeError):
    """The upload window cannot be computed here, so no object may be read."""


def earliest_read(ticket_issued_at: datetime) -> datetime:
    """When the object for a ticket issued at `ticket_issued_at` may first be read."""
    module = _upload_window()
    earliest: Callable[[datetime], datetime] = module.earliest_scan_read
    return earliest(ticket_issued_at)


# --- admission, the stream, verification ------------------------------------------


@dataclass(frozen=True, slots=True)
class Admission:
    """The result of asking whether the scanner may consume an object now."""

    gate: ObjectGate
    #: The identity captured before the read; set only when `gate` is `READY`.
    identity: ObjectIdentity | None = None
    #: When the window opens; set for `WINDOW_NOT_ELAPSED`, and a later slice
    #: defers the job to it.
    opens_at: datetime | None = None
    retry_after: timedelta | None = None

    @property
    def ready(self) -> bool:
        return self.gate is ObjectGate.READY


@dataclass(frozen=True, slots=True)
class ObjectCheck:
    """The object gate's conclusion after the read. `passed` is the first of three conditions."""

    gate: ObjectGate
    bytes_read: int = 0
    identity: ObjectIdentity | None = None
    #: SHA-256 (lowercase hex) of the bytes delivered by the one bounded stream, set
    #: only when the object gate passed. Independent of the ETag, which is identity
    #: evidence and never a digest.
    content_sha256: str | None = None
    #: What the structural gate reads: bounded windows over the same stream, sealed.
    #: Set only when the object gate passed. Not part of equality or the repr.
    probe: ContainerProbe | None = field(default=None, compare=False, repr=False)

    @property
    def passed(self) -> bool:
        return self.gate.passed


class ObjectChanged(ObjectSourceError):
    """The bytes being read are not the object that was inspected."""


class ObjectOversized(ObjectSourceError):
    """The stream outran the ceiling."""


class ObjectStream:
    """One bounded pass over one object, as the async iterable a scanner takes.

    Single use. It records *why* it stopped (`failure`) so that the worker can
    tell an oversized or changed object from an unreachable one even though the
    scanner only sees an `ObjectReadError`. It holds one chunk, plus the probe's bounded windows.
    """

    def __init__(
        self,
        source: ObjectSource,
        key: str,
        expected: ObjectIdentity,
        *,
        max_bytes: int,
        chunk_bytes: int,
    ) -> None:
        self._source = source
        self._key = key
        self._expected = expected
        self._max = max_bytes
        self._chunk = chunk_bytes
        self._used = False
        self.bytes_read = 0
        self.completed = False
        self.failure: ObjectGate | None = None
        #: The identity the provider sent with the read.
        self.observed: ObjectIdentity | None = None
        # The digest and the structural windows are fed from the bytes that already
        # flow through here: one read serves the scanner, the hash and the probe.
        self._sha256 = hashlib.sha256()
        self.probe = ContainerProbe()

    @property
    def content_sha256(self) -> str | None:
        """SHA-256 of the whole object as delivered, or `None` unless the stream completed.

        A stream that stopped early, failed or was cut off has hashed only a prefix,
        and a prefix digest must never be mistaken for the object's.
        """
        return self._sha256.hexdigest() if self.completed else None

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._run()

    async def _run(self) -> AsyncIterator[bytes]:
        if self._used:
            raise RuntimeError("an object stream is single use")
        self._used = True

        try:
            opened = await asyncio.to_thread(self._source.open, self._key)
        except Exception as error:
            self.failure = ObjectGate.UNREACHABLE
            raise ObjectSourceError("the object could not be opened") from error

        try:
            self.observed = opened.identity
            if not opened.identity.same_object(
                self._expected,
                compare_digest=False,
                last_modified_tolerance=OPEN_LAST_MODIFIED_TOLERANCE,
            ):
                self.failure = ObjectGate.CHANGED
                raise ObjectChanged("the object being read is not the one inspected")

            while True:
                # Never ask for more than one byte past the ceiling.
                want = min(self._chunk, self._max + 1 - self.bytes_read)
                try:
                    data = await asyncio.to_thread(opened.read, want)
                except Exception as error:
                    self.failure = ObjectGate.UNREACHABLE
                    raise ObjectSourceError("the object failed while being read") from error
                if not data:
                    break
                self.bytes_read += len(data)
                if self.bytes_read > self._max:
                    self.failure = ObjectGate.OVERSIZED
                    raise ObjectOversized("the object is larger than the scanner's ceiling")
                if self.bytes_read > self._expected.size:
                    self.failure = ObjectGate.CHANGED
                    raise ObjectChanged("the object delivered more bytes than it was inspected at")
                self._sha256.update(data)
                self.probe.feed(data)
                yield data

            if self.bytes_read != self._expected.size:
                self.failure = ObjectGate.CHANGED
                raise ObjectChanged("the object delivered fewer bytes than it was inspected at")
            self.probe.finish()
            self.completed = True
        finally:
            await asyncio.shield(asyncio.to_thread(_close_quietly, opened))


def _close_quietly(opened: OpenedObject) -> None:
    try:
        opened.close()
    except Exception:  # noqa: BLE001 - closing is best effort; the read already decided
        return


def _require_reference(ref: object) -> None:
    """Only a validated `ObjectReference` names an object; a string or a URL does not."""
    if not isinstance(ref, ObjectReference):
        raise TypeError("an object is named by an ObjectReference and nothing else")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ObjectReader:
    """Admits an object to the scanner, streams it within bounds, and re-checks it.

    ```
    admission = await reader.admit(ref, ticket_issued_at, expected_size=row_size)
    if admission.ready:
        stream = reader.stream(ref, admission)
        result = await scanner.scan(stream)
        check = await reader.verify(ref, admission, stream)   # object gate
    ```

    `check.passed` is necessary for a later `clean` and never sufficient.
    """

    def __init__(
        self,
        source: ObjectSource,
        *,
        max_bytes: int = MAX_SCAN_BYTES,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if not 0 < max_bytes <= MAX_SCAN_BYTES:
            raise ValueError("the ceiling cannot be raised past the ratified scanner limit")
        if not 0 < chunk_bytes <= 1024 * 1024:
            raise ValueError("the chunk size must be between 1 byte and 1 MiB")
        self._source = source
        self._max = max_bytes
        self._chunk = chunk_bytes
        self._clock = clock

    async def admit(
        self,
        ref: ObjectReference,
        ticket_issued_at: datetime,
        *,
        expected_size: int | None = None,
    ) -> Admission:
        """Whether the scanner may consume this object now.

        The window is checked before the store is touched. `expected_size` is
        the size the row recorded when the upload was confirmed; an object of a
        different size is not the object that was uploaded.
        """
        _require_reference(ref)
        opens_at = earliest_read(ticket_issued_at)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("the clock must be timezone-aware")
        if now < opens_at:
            return Admission(
                ObjectGate.WINDOW_NOT_ELAPSED, opens_at=opens_at, retry_after=opens_at - now
            )

        try:
            identity = await asyncio.to_thread(self._source.stat, ref.key)
        except Exception:  # noqa: BLE001 - any failure to ask is "could not ask"
            return Admission(ObjectGate.UNREACHABLE)
        if identity is None:
            return Admission(ObjectGate.MISSING)
        if identity.size > self._max:
            return Admission(ObjectGate.OVERSIZED)
        if expected_size is not None and identity.size != expected_size:
            return Admission(ObjectGate.CHANGED)
        if not identity.sufficient:
            return Admission(ObjectGate.IDENTITY_INSUFFICIENT)
        return Admission(ObjectGate.READY, identity=identity)

    def stream(self, ref: ObjectReference, admission: Admission) -> ObjectStream:
        """The bounded byte stream for an admitted object.

        Refuses anything but a `READY` admission, so a deferred or failed
        object cannot be read by passing its admission along.
        """
        _require_reference(ref)
        if not admission.ready or admission.identity is None:
            raise ValueError("only an admitted object can be streamed")
        return ObjectStream(
            self._source,
            ref.key,
            admission.identity,
            max_bytes=self._max,
            chunk_bytes=self._chunk,
        )

    async def verify(
        self, ref: ObjectReference, admission: Admission, stream: ObjectStream
    ) -> ObjectCheck:
        """Re-read the object's metadata and compare it with what was captured.

        Fails closed on every doubt: a stream that failed or did not finish, an
        object that is gone or cannot be asked, and any difference in size,
        ETag, version, last-modified or provider digest.
        """
        _require_reference(ref)
        if not admission.ready or admission.identity is None:
            raise ValueError("only an admitted object can be verified")
        read = stream.bytes_read
        if stream.failure is not None:
            return ObjectCheck(stream.failure, bytes_read=read)
        if not stream.completed:
            return ObjectCheck(ObjectGate.READ_INCOMPLETE, bytes_read=read)

        try:
            after = await asyncio.to_thread(self._source.stat, ref.key)
        except Exception:  # noqa: BLE001
            return ObjectCheck(ObjectGate.UNREACHABLE, bytes_read=read)
        if after is None:
            return ObjectCheck(ObjectGate.MISSING, bytes_read=read)
        if not after.same_object(admission.identity):
            return ObjectCheck(ObjectGate.CHANGED, bytes_read=read, identity=after)
        return ObjectCheck(
            ObjectGate.READY,
            bytes_read=read,
            identity=after,
            content_sha256=stream.content_sha256,
            probe=stream.probe,
        )
