# ruff: noqa: ANN401, S101
"""Stand-ins and constants for the restore suites (ADR 0013, `secure_files`, layer 5).

A bucket in a dict and a queue that answers as a live one. What the restore suites assert is
which key the row names, what the row says about it and what reached the bucket -- not a
provider -- so the provider is the one thing replaced. The real-service suites
(`test_restore_orchestration_real.py`) use a real store and a real scanner instead.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from koras_queue import Enqueued

OLD = b"the bytes the file had when it was scanned clean"
NEW = b"the bytes the backup holds, which are not those"
OLD_DIGEST = hashlib.sha256(OLD).hexdigest()
NEW_DIGEST = hashlib.sha256(NEW).hexdigest()
NAME = "contract.pdf"

TENANT = "11111111-1111-1111-1111-111111111111"
FILE = "22222222-2222-2222-2222-222222222222"


def final_key(tenant: str, file_id: str, name: str = NAME, generation: str | None = None) -> str:
    """The key a finalized upload of this file has: the one shape the scanner reads."""
    return f"tenants/{tenant}/documents/{file_id}/final/{generation or uuid.uuid4()}/{name}"


class MemStore:
    """A bucket in a dict, with the three things the assertions need: what was written, what was
    deleted, and what a signed URL for a key would read."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []
        self.fail_put = False
        #: Bytes the bucket hands back on the next `get` of a written key, instead of what was
        #: written: a provider that stored something else.
        self.corrupt_reads: bytes | None = None
        #: The digest each `put` was asked to have the provider verify, by key.
        self.asked_digest: dict[str, str | None] = {}

    def get(self, key: str) -> bytes | None:
        if self.corrupt_reads is not None and key in self.puts:
            return self.corrupt_reads
        return self.objects.get(key)

    def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        *,
        checksum_sha256: str | None = None,
    ) -> None:
        if self.fail_put:
            raise RuntimeError("the provider refused the write")
        self.puts.append(key)
        self.asked_digest[key] = checksum_sha256
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.deletes.append(key)
        self.objects.pop(key, None)

    def presign_download(self, key: str, filename: str, expires_in: int) -> str:
        return f"https://bucket.invalid/{key}?sig=1&exp={expires_in}"

    def fetch(self, url: str) -> bytes | None:
        """What a client holding this URL reads: the object at the key the URL names."""
        return self.objects.get(url.split("https://bucket.invalid/", 1)[1].split("?", 1)[0])


class Queue:
    """A queue that answers as a live one and remembers the delay it was asked for."""

    simulated = False

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[dict] = []

    async def enqueue(
        self,
        task: Any,
        *,
        tenant_id: str,
        payload: dict | None = None,
        idempotency_key: str = "",
        delay_seconds: float | None = None,
        **_: Any,
    ) -> Enqueued:
        if self.fail:
            raise ConnectionError("redis is unreachable")
        self.jobs.append(
            {
                "task": task.name,
                "tenant_id": tenant_id,
                "payload": dict(payload or {}),
                "key": idempotency_key,
                "delay": delay_seconds,
            }
        )
        return Enqueued(task=task.name, job_id=f"{task.name}:{idempotency_key}")

    async def aclose(self) -> None:
        return None
