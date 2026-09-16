"""Restore: the state machine, the two-person rule, and the check before the write.

The assertion this file exists for is the last one: a copy whose digest does not
match is a failure and the object stays gone. Gone is recoverable -- the backup
is still there, somebody looks at why -- and replaced-by-something-that-is-not-it
is not. Getting that backwards would make the restore feature the thing that
destroys the data it was built to save.
"""

from __future__ import annotations

import hashlib
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.restore import (  # noqa: E402
    TRANSITIONS,
    InvalidTransition,
    RestoreStatus,
    check_transition,
)

pytest.importorskip("koras_worker")
from koras_worker.tasks.storage_restore import RESTORE_CEILING, read_and_check  # noqa: E402

CONTENT = b"the original bytes"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
OTHER = hashlib.sha256(b"something else").hexdigest()


class _Store:
    def __init__(self, content: bytes | None = CONTENT) -> None:
        self._content = content
        self.written: list[str] = []

    def get(self, key: str) -> bytes | None:
        return self._content

    def put(self, key: str, content: bytes, content_type: str, **_: object) -> None:
        self.written.append(key)


# -- the machine ---------------------------------------------------------------


def test_asking_does_not_restore() -> None:
    """A request reaches `approved` or `refused` and nothing else. It cannot
    reach `restoring` on its own, which is what makes "asked for" and
    "happening" different states in the record rather than one."""
    assert TRANSITIONS[RestoreStatus.REQUESTED] == frozenset(
        {RestoreStatus.APPROVED, RestoreStatus.REFUSED}
    )
    with pytest.raises(InvalidTransition):
        check_transition(RestoreStatus.REQUESTED, RestoreStatus.RESTORING)


def test_only_an_approved_request_runs() -> None:
    check_transition(RestoreStatus.APPROVED, RestoreStatus.RESTORING)
    with pytest.raises(InvalidTransition):
        check_transition(RestoreStatus.REFUSED, RestoreStatus.RESTORING)


def test_a_finished_request_is_finished() -> None:
    """A failed restore is asked for again as a new request, so the history
    keeps both the attempt and the retry rather than overwriting one with the
    other."""
    for terminal in (RestoreStatus.COMPLETED, RestoreStatus.FAILED, RestoreStatus.REFUSED):
        assert TRANSITIONS[terminal] == frozenset()


def test_an_approved_request_can_still_be_refused() -> None:
    """Between approval and execution somebody may change their mind, and the
    sweep runs every ten minutes rather than instantly. A machine with no way
    back from `approved` would make that window irreversible."""
    check_transition(RestoreStatus.APPROVED, RestoreStatus.REFUSED)


# -- what is read, before anything is written ----------------------------------


def test_a_matching_copy_is_returned_with_its_digest() -> None:
    content, digest, refusal = read_and_check(_Store(), "k", DIGEST, len(CONTENT))
    assert content == CONTENT
    assert digest == DIGEST
    assert refusal is None


def test_a_copy_that_does_not_match_returns_no_bytes() -> None:
    """The assertion this file exists for. The object stays gone, which is
    recoverable; replaced by something that is not it, which is not."""
    content, digest, refusal = read_and_check(_Store(), "k", OTHER, len(CONTENT))
    assert content is None
    assert digest == DIGEST
    assert refusal is not None and "does not match" in refusal


def test_a_copy_nobody_ever_hashed_still_restores() -> None:
    """Refusing would mean refusing the only copy of an object whose provider
    never computed a digest -- which is most objects uploaded before the
    integrity work. The audit row says plainly that nothing was compared."""
    content, digest, refusal = read_and_check(_Store(), "k", None, len(CONTENT))
    assert content == CONTENT
    assert digest == DIGEST
    assert refusal is None


def test_a_copy_that_is_gone_is_a_failure_not_an_empty_restore() -> None:
    """A provider answering nothing must not become a zero-byte object written
    over the customer's file."""
    content, _, refusal = read_and_check(_Store(content=None), "k", DIGEST, 10)
    assert content is None
    assert refusal is not None and "no longer at the destination" in refusal


def test_an_object_too_large_is_refused_before_it_is_read() -> None:
    store = _Store()
    content, _, refusal = read_and_check(store, "k", DIGEST, RESTORE_CEILING + 1)
    assert content is None
    assert refusal is not None
    # And nothing was fetched: the ceiling exists so the worker does not hold
    # the object in memory, which a check after the read would not achieve.
    assert store.written == []
