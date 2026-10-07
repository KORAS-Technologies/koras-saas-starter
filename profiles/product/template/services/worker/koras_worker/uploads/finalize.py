"""Immutable upload finalization (ADR 0013, `secure_files`).

Nothing reads a key a client could write.

A signed PUT is authority to write one key, and it outlives its own expiry (a request
begun inside the window was measured running on for about 150 seconds, replacing the
object after a scanner had read it and committed `clean`; proven against a real provider
in Docoris). Nothing the product controls bounds that, and no provider identity
(versioning, checksum, conditional write) is available to bind a verdict to bytes. So the
key a ticket was signed for is not what is scanned or released.

    ticket -> tenants/<t>/<cat>/<file>/incoming/<upload-id>/<name>      client-writable
    finalize -> tenants/<t>/<cat>/<file>/final/<generation>/<name>      never ticketed
    scan, verdict, release -> the final key only

**What finalization does, in order.** After `FINALIZE_DELAY_SECONDS` from the ticket's
issue (the window, the longest observed in-flight request, and the margin), it
(1) copies the incoming object server-side to a final key whose generation is a fresh
UUID for this attempt, (2) checks the copy is the announced size, (3) in one
transaction swaps `files.storage_key` from the incoming key to the final one **only
while the row still holds that incoming key, is `ready` and is `pending`**, and (4)
deletes the incoming object, best effort.

**Why the horizon is not what makes it safe.** A write that lands after the copy lands
on the incoming key, which nothing reads, so the final bytes are fixed at the copy and
whatever a late request does is invisible. A write that lands *during* the copy is
copied or not as the provider decides; either way the final object is one whole object
whose bytes then never change, and it is that object that is scanned. The delay only
keeps an honest slow upload from being cut short.

**Why the final key is exclusive.** The generation is unique per attempt, so two
concurrent finalizations never write one key. The swap is compare-and-set on the
incoming key, so exactly one of them owns the row, and the other deletes the key it
wrote. A final key that no row references is nobody's: it is deleted by the attempt
that wrote it, or, if that cannot be done, it is an object with no row that
reconciliation already counts (`storage.reconcile.orphan_found`).

**Checksum-bound promotion.** The key a ticket was signed for is not the only thing a
signed PUT does not confine: the provider executes an *unsigned* `x-amz-copy-source`
header as a server-side copy from any key in the bucket, another tenant's final object
included, and it keeps whatever digest the request *claimed*. So nothing the provider
says about an incoming object is evidence of its bytes. The file's row carries the
SHA-256 the upload was authorized for, bound when the ticket was issued and never
written by the client afterwards, and finalization promotes an object only if:

1. the row has a well-formed claim (a row without one is held, never given one here);
2. the incoming object carries the ticket's own upload id as the provenance a plain PUT
   stores (`koras_storage.upload_guard_headers`; a provider copy carries its *source's*
   metadata), and that id is **exactly equal** to the one in the incoming key;
3. the SHA-256 this process computes over the incoming bytes equals the claim; and
4. after the copy, the SHA-256 it computes over the **final** bytes equals the claim
   too. The final key is the one thing no client can write, so this is the digest of
   exactly the bytes that will be scanned and released, and a late write to the incoming
   key cannot change it.

Any failure holds the file `pending` with a closed failure word (`FinalizeFailure`;
`integrity_mismatch` for a digest or provenance that is not the claim's), deletes any
final object this attempt wrote, and never swaps the row. A match is
`checksum_verified_at`, by this process's own computation and not the provider's
say-so. Knowing another tenant's key *and* its digest passes steps 1 and 3 for copied
bytes; what stops that copy is the signed copy-source preconditions (and step 2 if a
provider ignored them), which the provider matrix in
`tests/integration/test_upload_finalization_provider.py` exercises against a real store.

**Failure atomicity.**
- copy fails or the source is missing or the wrong size: nothing was switched; the file
  stays `pending` with a recorded reason, and any final object this attempt wrote is
  deleted;
- copy succeeds, the swap does not commit: the same, and the file is still on its incoming
  key so the next attempt starts again with a new generation;
- the swap commits, the incoming delete fails: the row is final and correct, and the
  leftover incoming object is an orphan for reconciliation;
- the swap commits, whatever follows it fails: the file is final and `pending`, which is
  not releasable;
- a retry on a finalized file finds a final key and does nothing.

This module reaches the store through the five calls below, none of which signs a URL, and
reads and writes only the tenant's own file row, as that tenant.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from koras_storage import IntegrityRefused
from sqlalchemy import text

from ._audit import emit_and_commit

logger = logging.getLogger(__name__)


class FinalizeStore(Protocol):
    """What finalization asks of a bucket: no signing and no listing."""

    def head(self, key: str) -> int | None: ...

    def copy(self, source_key: str, dest_key: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def provenance(self, key: str) -> str | None:
        """The upload id a plain PUT stored on the object, or None."""
        ...

    def sha256(self, key: str) -> str | None:
        """The SHA-256, as hex, this process computes over the object's bytes; None if absent."""
        ...


class FinalizeStoreUnavailable(RuntimeError):
    """The worker has no store to copy within, so nothing may be finalized or scanned."""


class FinalizeFailure(StrEnum):
    """Why a file was not finalized. The values are the `scan_failure` words recorded for it
    (the closed vocabulary of migration 00039, shared with the scanner that follows); this
    module names them without depending on the scanner."""

    OBJECT_UNREACHABLE = "object_unreachable"
    OBJECT_CHANGED = "object_changed"
    INTEGRITY_MISMATCH = "integrity_mismatch"
    MISCONFIGURED = "misconfigured"


class FinalizeKind(StrEnum):
    #: This attempt copied the object and the row now references the final key.
    FINALIZED = "finalized"
    #: The row already references a key no ticket was signed for; nothing was done.
    ALREADY_FINAL = "already_final"
    #: The delay has not elapsed. Nothing was read or written.
    DEFERRED = "deferred"
    #: Not finalized; the file stays `pending` and the reason is the closed `ScanFailure`.
    HELD = "held"
    #: No ready, pending row of this tenant, or the row changed under the attempt.
    NOT_ELIGIBLE = "not_eligible"


@dataclass(frozen=True, slots=True)
class Finalization:
    kind: FinalizeKind
    failure: FinalizeFailure | None = None
    opens_at: datetime | None = None
    #: The final key, for the two outcomes that end with the row on one. Never logged or audited.
    key: str | None = None


_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
_ROW = text(
    "select storage_key, size_bytes, created_at, checksum_sha256 from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)
#: The swap. Compare-and-set on the incoming key: it applies only while the row still
#: references the object this attempt copied, so a concurrent attempt, a restore, a
#: delete or a verdict leaves it with no rows and the attempt's own object is discarded.
#: The backup columns are reset so the final object, and not the incoming one, is what
#: the next backup pass copies (the same reset a restore's replacement makes).
_SWAP = text(
    "update public.files set storage_key = :final_key, checksum_verified_at = :verified, "
    " backup_status = 'none', backed_up_at = null "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' and storage_key = :incoming_key "
    "returning id"
)


def _window() -> Any:  # noqa: ANN401 - a module, reached by name
    """The API's shared upload-window module. Missing means nothing may be finalized."""
    try:
        return importlib.import_module("koras_api.core.upload_window")
    except ImportError as error:
        raise FinalizeStoreUnavailable(
            "the shared upload-window module is not on this worker's path"
        ) from error


def _held(failure: FinalizeFailure) -> Finalization:
    return Finalization(FinalizeKind.HELD, failure=failure)


def _discard(store: FinalizeStore, key: str) -> None:
    """Delete an object this attempt wrote and no row references. Never raises."""
    try:
        store.delete(key)
    except Exception as error:  # noqa: BLE001 - an orphan for reconciliation, not a reason to fail
        logger.error(
            "finalize: could not remove an unreferenced final object (%s)", type(error).__name__
        )


class UploadFinalizer:
    """Finalizes one file's upload, as one tenant, against one store."""

    def __init__(self, store: FinalizeStore) -> None:
        self._store = store

    async def finalize(
        self,
        session: Any,  # noqa: ANN401 - the caller's session, with no uncommitted work
        *,
        tenant_id: str,
        file_id: str,
        now: datetime,
    ) -> Finalization:
        ids = {"tenant_id": tenant_id, "file_id": file_id}
        window = _window()
        row = await self._read(session, ids)
        if row is None:
            return Finalization(FinalizeKind.NOT_ELIGIBLE)

        incoming_key = str(row["storage_key"])
        if not window.is_incoming_key(incoming_key):
            return Finalization(FinalizeKind.ALREADY_FINAL, key=incoming_key)

        # The key must belong to this tenant and file before any store call: a row naming
        # another tenant's object would otherwise be copied, re-pointed and deleted.
        parts = incoming_key.split("/")
        if parts[1:2] != [tenant_id] or parts[3:4] != [file_id]:
            logger.error("finalize: file %s has an incoming key that is not its own", file_id)
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)

        opens_at = window.earliest_finalization(row["created_at"])
        if now < opens_at:
            return Finalization(FinalizeKind.DEFERRED, opens_at=opens_at)

        # The content claim the upload was authorized for. Never supplied here: a row with
        # none is a ticket from before the claim was required, and it is held.
        claim = str(row["checksum_sha256"] or "")
        if _SHA256.match(claim) is None:
            logger.error("finalize: file %s has no checksum bound to its upload", file_id)
            return _held(FinalizeFailure.INTEGRITY_MISMATCH)

        try:
            final_key = window.final_key_for(incoming_key, str(uuid.uuid4()))
        except ValueError:
            # An `incoming` segment in a shape this code did not write: never scanned,
            # never guessed at.
            logger.error("finalize: file %s has an incoming key it cannot finalize", file_id)
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)

        verified_at = await self._copy(
            incoming_key, final_key, row["size_bytes"], claim, parts[5], now
        )
        if isinstance(verified_at, Finalization):
            return await self._unless_moved_on(session, ids, incoming_key, verified_at)

        try:
            await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
            swapped = (
                await session.execute(
                    _SWAP,
                    {
                        **ids,
                        "final_key": final_key,
                        "incoming_key": incoming_key,
                        "verified": verified_at[0],
                    },
                )
            ).first()
        except BaseException:
            # The statement did not complete, so nothing committed: no row can reference
            # the key this attempt wrote.
            await session.rollback()
            _discard(self._store, final_key)
            raise
        if swapped is None:
            await session.rollback()
            _discard(self._store, final_key)
            return Finalization(FinalizeKind.NOT_ELIGIBLE)
        try:
            # The event is written by the registered sink on this session and commits once:
            # the swap and its event are one transaction.
            await emit_and_commit(
                session,
                tenant_id=tenant_id,
                action="storage.upload.finalized",
                file_id=file_id,
                corroborated=verified_at[0] is not None,
            )
        except BaseException:
            # A commit that raises may or may not have landed. Deleting a referenced
            # object would be the one unrecoverable mistake here, so the key is removed
            # only when the row is read back and does not reference it; when that cannot
            # be established it stays, an orphan for reconciliation.
            await session.rollback()
            if await self._references(session, ids, final_key) is False:
                _discard(self._store, final_key)
            raise

        # The row is final. The incoming object is now referenced by nothing and a late
        # write to it is invisible; removing it is tidiness, and a failure is an orphan.
        try:
            await asyncio.to_thread(self._store.delete, incoming_key)
        except Exception as error:  # noqa: BLE001
            logger.error(
                "finalize: file %s is final but its incoming object was not removed (%s)",
                file_id,
                type(error).__name__,
            )
        return Finalization(FinalizeKind.FINALIZED, key=final_key)

    @staticmethod
    async def _read(
        session: Any,  # noqa: ANN401
        ids: dict[str, str],
    ) -> dict[str, Any] | None:
        """The tenant's own ready, pending row, or nothing. A read, ended before returning."""
        try:
            await session.execute(_AS_TENANT, {"tenant_id": ids["tenant_id"]})
            found = (await session.execute(_ROW, ids)).mappings().first()
            row = dict(found) if found is not None else None
            # Ends the read: no transaction is held open across a copy.
            await session.rollback()
        except BaseException:
            await session.rollback()
            raise
        return row

    async def _unless_moved_on(
        self,
        session: Any,  # noqa: ANN401
        ids: dict[str, str],
        incoming_key: str,
        held: Finalization,
    ) -> Finalization:
        """A failure is reported only if the file is still waiting on the key that failed.

        A concurrent attempt that won deletes the incoming object after it commits, so the
        loser finds it missing and would call a healthy, finalized file unreachable. Read
        the row again: if it no longer names the incoming key, someone finished the job and
        there is nothing to record.
        """
        try:
            row = await self._read(session, ids)
        except Exception:  # noqa: BLE001 - cannot tell; the failure stands
            return held
        if row is None:
            return Finalization(FinalizeKind.NOT_ELIGIBLE)
        current = str(row["storage_key"])
        if current != incoming_key and not _window().is_incoming_key(current):
            return Finalization(FinalizeKind.ALREADY_FINAL, key=current)
        return held

    @staticmethod
    async def _references(
        session: Any,  # noqa: ANN401
        ids: dict[str, str],
        key: str,
    ) -> bool | None:
        """Whether the row now references `key`; `None` when that cannot be established."""
        try:
            await session.execute(_AS_TENANT, {"tenant_id": ids["tenant_id"]})
            found = (
                (
                    await session.execute(
                        text(
                            "select storage_key from public.files "
                            "where id = cast(:file_id as uuid) "
                            "and tenant_id = cast(:tenant_id as uuid)"
                        ),
                        ids,
                    )
                )
                .mappings()
                .first()
            )
            await session.rollback()
        except Exception:  # noqa: BLE001
            return None
        return found is not None and found["storage_key"] == key

    async def _copy(
        self,
        incoming_key: str,
        final_key: str,
        size: int,
        claim: str,
        upload_id: str,
        now: datetime,
    ) -> tuple[datetime | None] | Finalization:
        """Check, copy and check again. A one-tuple of `checksum_verified_at`, else the hold."""
        store = self._store
        try:
            found = await asyncio.to_thread(store.head, incoming_key)
        except Exception as error:  # noqa: BLE001
            logger.error(
                "finalize: the incoming object could not be inspected (%s)", type(error).__name__
            )
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)
        if found is None:
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)
        if found != size:
            return _held(FinalizeFailure.OBJECT_CHANGED)

        # Before any byte is copied: the object must be what a plain PUT of this ticket stores,
        # and must hash to the claim. Neither says anything about a late write, so the final
        # object is hashed again below.
        try:
            stored_upload = await asyncio.to_thread(store.provenance, incoming_key)
            incoming_digest = await asyncio.to_thread(store.sha256, incoming_key)
        except Exception as error:  # noqa: BLE001
            logger.error(
                "finalize: the incoming object could not be verified (%s)", type(error).__name__
            )
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)
        if incoming_digest is None:
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)
        if stored_upload != upload_id or incoming_digest.lower() != claim:
            logger.error("finalize: an incoming object is not the upload its ticket authorized")
            return _held(FinalizeFailure.INTEGRITY_MISMATCH)

        try:
            await asyncio.to_thread(store.copy, incoming_key, final_key)
        except Exception as error:  # noqa: BLE001 - CopyRefused, IntegrityRefused, a dropped connection
            _discard(store, final_key)
            logger.error("finalize: the copy failed (%s)", type(error).__name__)
            return _held(
                FinalizeFailure.INTEGRITY_MISMATCH
                if isinstance(error, IntegrityRefused)
                else FinalizeFailure.OBJECT_UNREACHABLE
            )

        try:
            copied = await asyncio.to_thread(store.head, final_key)
            final_digest = await asyncio.to_thread(store.sha256, final_key)
        except Exception as error:  # noqa: BLE001
            _discard(store, final_key)
            logger.error("finalize: the copy could not be inspected (%s)", type(error).__name__)
            return _held(FinalizeFailure.OBJECT_UNREACHABLE)
        if copied != size:
            _discard(store, final_key)
            return _held(FinalizeFailure.OBJECT_CHANGED)
        # The final key is the one no client can write: these are the bytes that will be
        # scanned and released, and they are promoted only if they are the claimed ones.
        if final_digest is None or final_digest.lower() != claim:
            _discard(store, final_key)
            logger.error("finalize: the copied object does not hash to the upload's claim")
            return _held(FinalizeFailure.INTEGRITY_MISMATCH)
        return (now,)
