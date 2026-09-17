"""The copy, and the comparison that decides whether it was worth anything.

The assertion this file exists for is the one that reads as a failure and is
not: an object neither end holds a comparable digest for is `copied`, never
`failed`. Getting that backwards would report every large object as corrupt on
the first night and teach whoever reads the console to ignore the number --
which is how a real mismatch, months later, goes unread.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_storage import CopyRefused, Destination, IntegrityRefused, Provider  # noqa: E402
from koras_worker.tasks.storage_backup import (  # noqa: E402
    STREAM_CEILING,
    BackupSettings,
    back_up_tenant_objects,
    backup_key_for,
    copy_one,
    date_orphaned_copies,
    destination_from,
    retire_expired_copies,
    streams_through_here,
    verdict,
)

TENANT = "11111111-1111-1111-1111-111111111111"
DIGEST = hashlib.sha256(b"one").hexdigest()
OTHER = hashlib.sha256(b"two").hexdigest()

TARGET = Destination(Provider.SUPABASE, "http://localhost:9000", "backups", "us-east-1", "k", "s")


class _File:
    def __init__(
        self,
        file_id: str = "22222222-2222-2222-2222-222222222222",
        storage_key: str = "tenants/t/documents/f1/a.pdf",
        size_bytes: int | None = 10,
        checksum_sha256: str | None = DIGEST,
    ) -> None:
        self.id = file_id
        self.tenant_id = TENANT
        self.storage_key = storage_key
        self.size_bytes = size_bytes
        self.checksum_sha256 = checksum_sha256


class _Catalogued:
    def __init__(self, row_id: str = "33333333-3333-3333-3333-333333333333") -> None:
        self.id = row_id
        self.tenant_id = TENANT
        self.backup_key = "tenants/t/documents/f1/a.pdf"


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, due: list[Any] | None = None, catalogued: list[Any] | None = None) -> None:
        self._due = due or []
        self._catalogued = catalogued or []
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        text = str(statement)
        self.statements.append((text, parameters))
        # The catalogue first: the orphan query names both tables, because it
        # asks which catalogue rows have no file behind them any more.
        if "from public.file_backups" in text and text.strip().startswith("select"):
            return _Result(list(self._catalogued))
        if "from public.files" in text and text.strip().startswith("select"):
            return _Result(list(self._due))
        return _Result([])

    async def commit(self) -> None:
        self.commits += 1

    def written(self, fragment: str) -> list[dict[str, Any]]:
        return [p or {} for text, p in self.statements if fragment in text]


class _Store:
    """Both ends of the copy, so that a test can make the two disagree."""

    def __init__(
        self,
        *,
        digest: str | None = DIGEST,
        content: bytes | None = b"one",
        refuse: bool = False,
        reject: bool = False,
        refuse_copy: bool = False,
    ) -> None:
        self._digest = digest
        self._content = content
        self._refuse = refuse
        #: The destination will not copy server-side but will take the bytes,
        #: which is Supabase's S3 for any key containing a space.
        self._refuse_copy = refuse_copy
        #: The destination compared the bytes against the digest it was sent
        #: and disagreed, which is the control working.
        self._reject = reject
        self.copied: list[tuple[str, str]] = []
        self.put_keys: list[str] = []
        self.put_digests: list[str | None] = []
        self.deleted: list[str] = []

    def get(self, key: str) -> bytes | None:
        return self._content

    def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        *,
        checksum_sha256: str | None = None,
    ) -> None:
        if self._reject:
            raise IntegrityRefused("the bytes do not match the digest")
        self.put_keys.append(key)
        self.put_digests.append(checksum_sha256)

    def copy(self, source_key: str, dest_key: str, *, dest: Destination | None = None) -> None:
        if self._refuse_copy:
            raise CopyRefused("the destination will not copy this key server-side")
        if self._refuse:
            raise RuntimeError("the destination refused the copy")
        self.copied.append((source_key, dest_key))

    def checksum(self, key: str) -> str | None:
        return self._digest

    def delete(self, key: str) -> None:
        if self._refuse:
            raise RuntimeError("the destination refused the delete")
        self.deleted.append(key)


# -- the three outcomes --------------------------------------------------------


def test_two_matching_digests_are_a_backup() -> None:
    outcome = verdict(DIGEST, DIGEST)
    assert outcome.status == "verified"
    assert outcome.note is None


def test_two_digests_that_differ_are_a_failure_and_say_which_way() -> None:
    outcome = verdict(DIGEST, OTHER)
    assert outcome.status == "failed"
    assert outcome.source_digest == DIGEST
    assert outcome.backup_digest == OTHER


@pytest.mark.parametrize(
    ("source", "copy"),
    [(None, DIGEST), (DIGEST, None), (None, None)],
)
def test_nothing_to_compare_is_copied_rather_than_failed(
    source: str | None, copy: str | None
) -> None:
    """A provider computes a SHA-256 only when the upload asked it to, so no
    digest is the ordinary case. Reporting it as a mismatch would call every
    large object corrupt on the first night."""
    outcome = verdict(source, copy)
    assert outcome.status == "copied"
    assert outcome.note is not None and "not verified" in outcome.note


# -- how the copy is made ------------------------------------------------------


def test_a_same_provider_copy_never_reads_the_bytes() -> None:
    source = _Store()
    target = _Store()
    outcome = copy_one(
        source,  # type: ignore[arg-type]
        target,  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=10,
        streaming=False,
    )
    assert outcome.status == "verified"
    assert source.copied == [("tenants/t/documents/f1/a.pdf", "tenants/t/documents/f1/a.pdf")]
    assert target.put_keys == []


def test_a_cross_provider_copy_hashes_what_it_actually_read() -> None:
    """The stronger statement of the two: the digest is of the bytes this
    process read from the source and wrote to the destination, rather than of
    whatever each provider says it holds."""
    source = _Store(content=b"one", digest=None)
    target = _Store(digest=DIGEST)
    outcome = copy_one(
        source,  # type: ignore[arg-type]
        target,  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=3,
        streaming=True,
    )
    assert outcome.status == "verified"
    assert outcome.source_digest == DIGEST
    assert target.put_keys == ["tenants/t/documents/f1/a.pdf"]
    # The digest goes *with* the write, not after it. Without this the
    # destination stores no SHA-256, `checksum()` answers None, and every
    # cross-provider copy reads `copied` for ever -- a backup nobody could
    # confirm, from the job whose whole purpose is confirming backups.
    assert target.put_digests == [DIGEST]


def test_an_object_too_large_to_stream_is_left_rather_than_loaded() -> None:
    source = _Store()
    outcome = copy_one(
        source,  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=STREAM_CEILING + 1,
        streaming=True,
    )
    assert outcome.status == "skipped"
    assert source.copied == [] and source.put_keys == []


def test_an_object_gone_from_the_source_is_skipped_not_failed() -> None:
    """Between the index read and the copy, a purge can happen. That is not a
    backup failure; there is nothing left to back up."""
    outcome = copy_one(
        _Store(content=None),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=10,
        streaming=True,
    )
    assert outcome.status == "skipped"


def test_the_copy_keeps_the_source_key() -> None:
    """Objects here are immutable -- a key carries the file's id and nothing
    overwrites one -- so a mirror is a complete backup of current state and a
    restore does not need a catalogue lookup to find the bytes."""
    assert backup_key_for("tenants/t/documents/f1/a.pdf") == "tenants/t/documents/f1/a.pdf"


# -- where the copy goes -------------------------------------------------------


def test_a_backup_into_the_bucket_it_came_from_is_refused() -> None:
    """The one mistake that looks like success in every log line."""
    with pytest.raises(ValueError, match="already in"):
        destination_from(
            BackupSettings(storage_bucket="uploads", storage_backup_bucket="uploads")
        )


def test_no_destination_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="nowhere to copy"):
        destination_from(BackupSettings(storage_bucket="uploads"))


def test_a_provider_name_this_product_does_not_serve_is_refused() -> None:
    """A typo resolving to the default is a backup written somewhere nobody
    chose, and it would report as a success."""
    with pytest.raises(ValueError, match="not a provider"):
        destination_from(
            BackupSettings(
                storage_bucket="uploads",
                storage_backup_bucket="backups",
                storage_backup_provider="azure-blob",
            )
        )


def test_an_unset_endpoint_is_the_same_project_and_copies_server_side() -> None:
    config = BackupSettings(
        storage_endpoint="http://localhost:9000",
        storage_bucket="uploads",
        storage_backup_bucket="backups",
    )
    assert streams_through_here(config) is False
    assert destination_from(config).endpoint == "http://localhost:9000"


def test_a_destination_at_another_endpoint_streams() -> None:
    config = BackupSettings(
        storage_endpoint="http://localhost:9000",
        storage_bucket="uploads",
        storage_backup_bucket="backups",
        storage_backup_endpoint="https://account.r2.cloudflarestorage.com",
        storage_backup_provider="cloudflare-r2",
    )
    assert streams_through_here(config) is True
    assert destination_from(config).provider is Provider.CLOUDFLARE_R2


# -- the run -------------------------------------------------------------------


async def test_a_run_catalogues_and_marks_each_object() -> None:
    session = _Session(due=[_File()])
    summary = await back_up_tenant_objects(
        session,  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        streaming=False,
        limit=10,
    )
    assert (summary.considered, summary.verified, summary.partial) == (1, 1, False)

    catalogued = session.written("insert into public.file_backups")
    assert catalogued and catalogued[0]["status"] == "verified"
    assert catalogued[0]["destination"] == "backups"

    marked = session.written("update public.files set backup_status")
    assert marked and marked[0]["status"] == "verified"


async def test_a_run_that_hits_its_limit_reports_itself_partial() -> None:
    """A count from an unfinished pass, presented as a total, is worse than no
    count -- the rule the reconciliation sweep already follows."""
    session = _Session(
        due=[_File(file_id=f"4444444{n}-2222-2222-2222-222222222222") for n in range(3)]
    )
    summary = await back_up_tenant_objects(
        session,  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        streaming=False,
        limit=3,
    )
    assert summary.partial is True


async def test_a_provider_refusing_one_object_does_not_stop_the_run() -> None:
    session = _Session(due=[_File()])
    summary = await back_up_tenant_objects(
        session,  # type: ignore[arg-type]
        _Store(refuse=True),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        streaming=False,
        limit=10,
    )
    assert summary.failed == 1
    marked = session.written("update public.files set backup_status")
    # `failed` leaves `backed_up_at` null: there is no moment at which this
    # object was backed up, and a date there would read as though there were.
    assert marked[0]["status"] == "failed" and marked[0]["at"] is None


async def test_every_run_is_recorded_for_the_tenant_whose_objects_it_touched() -> None:
    session = _Session(due=[_File()])
    await back_up_tenant_objects(
        session,  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        streaming=False,
        limit=10,
    )
    recorded = session.written("insert into public.audit_events")
    assert recorded and recorded[0]["action"] == "storage.backup.run"
    assert recorded[0]["outcome"] == "ok"
    # On the tenant's own context, because the audit table admits a row only
    # for the tenant it belongs to.
    assert any("set_config('app.tenant_id'" in text for text, _ in session.statements)


async def test_a_run_with_a_failure_is_not_recorded_as_ok() -> None:
    session = _Session(due=[_File()])
    await back_up_tenant_objects(
        session,  # type: ignore[arg-type]
        _Store(refuse=True),  # type: ignore[arg-type]
        _Store(),  # type: ignore[arg-type]
        TARGET,
        streaming=False,
        limit=10,
    )
    recorded = session.written("insert into public.audit_events")
    assert recorded[0]["outcome"] == "failed"


# -- the copy outlives the object ----------------------------------------------


async def test_a_copy_whose_object_is_gone_starts_its_own_clock() -> None:
    """A catalogue row deleted alongside the object would be insurance that
    expires at the moment of the accident."""
    session = _Session(catalogued=[_Catalogued()])
    dated = await date_orphaned_copies(session, days=30)  # type: ignore[arg-type]
    assert dated == 1
    set_expiry = session.written("set expires_at")
    assert set_expiry and set_expiry[0]["days"] == 30


async def test_a_copy_past_its_date_goes_object_first_then_row() -> None:
    session = _Session(catalogued=[_Catalogued()])
    target = _Store()
    retired, stuck = await retire_expired_copies(session, target, limit=10)  # type: ignore[arg-type]
    assert (retired, stuck) == (1, 0)
    assert target.deleted == ["tenants/t/documents/f1/a.pdf"]
    order = [text for text, _ in session.statements]
    assert any("delete from public.file_backups" in text for text in order)


async def test_a_destination_that_will_not_delete_keeps_the_catalogue_row() -> None:
    """A bucket refusing a delete is a leak to report, not a reason to drop the
    only record that the copy exists."""
    session = _Session(catalogued=[_Catalogued()])
    retired, stuck = await retire_expired_copies(
        session,  # type: ignore[arg-type]
        _Store(refuse=True),  # type: ignore[arg-type]
        limit=10,
    )
    assert (retired, stuck) == (0, 1)
    assert not session.written("delete from public.file_backups")


async def test_a_destination_that_rejects_the_bytes_is_a_failure_not_a_retry() -> None:
    """A provider comparing what it received against the digest it was sent,
    and disagreeing, is the control working. Writing the bytes again without
    the digest would turn a caught corruption into a catalogued backup."""
    outcome = copy_one(
        _Store(content=b"one"),  # type: ignore[arg-type]
        _Store(reject=True),  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=3,
        streaming=True,
    )
    assert outcome.status == "failed"
    assert outcome.note is not None and "not matching" in outcome.note


def test_a_destination_with_no_checksum_support_still_gets_the_copy() -> None:
    """A provider that cannot answer a SHA-256 leaves the copy at `copied`.
    That is an honest report of an unverifiable copy, and it is better than no
    copy: the object is still somewhere else."""
    target = _Store(digest=None)
    outcome = copy_one(
        _Store(content=b"one"),  # type: ignore[arg-type]
        target,  # type: ignore[arg-type]
        TARGET,
        source_key="tenants/t/documents/f1/a.pdf",
        backup_key="tenants/t/documents/f1/a.pdf",
        size_bytes=3,
        streaming=True,
    )
    assert outcome.status == "copied"
    assert target.put_keys == ["tenants/t/documents/f1/a.pdf"]


def test_a_refused_server_side_copy_is_streamed_instead() -> None:
    """A provider that will not copy is not a provider that cannot back up.

    Supabase's S3 gateway refuses `CopyObject` for any key with a space in it,
    with an empty error code so no code list could have matched, while
    `HeadObject` on the same key succeeds. Four of the dev estate's six objects
    were recorded `failed` night after night and the run still reported `ok`.

    Reading the bytes and writing them works on exactly those keys, so the
    fallback is not a lesser copy -- it is the only one available, and it is the
    one that can reach `verified`, because the digest is computed here and sent
    with the write.
    """
    source = _Store(refuse_copy=True, content=b"one")
    target = _Store(digest=hashlib.sha256(b"one").hexdigest())

    outcome = copy_one(
        source,
        target,
        TARGET,
        source_key="tenants/t/f/Homework Packet.pdf",
        backup_key="tenants/t/f/Homework Packet.pdf",
        size_bytes=3,
        streaming=False,
    )

    assert outcome.status == "verified", outcome.note
    assert target.put_keys == ["tenants/t/f/Homework Packet.pdf"]
    # The digest went with the write. Without it the destination stores no
    # SHA-256 and this could never be better than `copied`.
    assert target.put_digests == [hashlib.sha256(b"one").hexdigest()]


def test_the_stream_ceiling_still_applies_to_a_refused_copy() -> None:
    """The fallback is the cross-provider path, and it has a bound.

    A refusal must not become a way to pull an object of any size into a
    worker's memory, which is the thing `STREAM_CEILING` exists to prevent.
    """
    source = _Store(refuse_copy=True)
    outcome = copy_one(
        source,
        _Store(),
        TARGET,
        source_key="tenants/t/f/big file.bin",
        backup_key="tenants/t/f/big file.bin",
        size_bytes=STREAM_CEILING + 1,
        streaming=False,
    )
    assert outcome.status == "skipped"


def test_an_integrity_refusal_is_never_streamed_around() -> None:
    """Guards the guard, and the more important half of it.

    "Will not copy by that route" and "those bytes do not match" are different
    claims. Answering the second by writing the bytes another way is how a
    corrupt object becomes a backup, so the fallback must not be reachable from
    it. `IntegrityRefused` is raised by `put`, on the path the fallback uses.
    """
    source = _Store(refuse_copy=True, content=b"one")
    target = _Store(reject=True)

    outcome = copy_one(
        source,
        target,
        TARGET,
        source_key="tenants/t/f/a file.pdf",
        backup_key="tenants/t/f/a file.pdf",
        size_bytes=3,
        streaming=False,
    )

    assert outcome.status == "failed"
    assert outcome.note == "the destination rejected the bytes as not matching"
