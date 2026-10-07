# ruff: noqa: ANN401
"""A bucket in a dict for the upload-finalization tests (ADR 0013, `secure_files`).

It is two things at once, because the finalizer and a client with a signed URL each see
one bucket:

* `FinalizeStore` (`head`, `copy`, `delete`, `provenance`, `sha256`) for `UploadFinalizer`;
* `client_put`, which is what a holder of a signed URL can do: write the one key the
  URL was signed for, and nothing else. `grant` records the keys a ticket was signed for.
  A plain PUT stores the ticket's upload id as provenance (the signed `x-amz-meta-koras-upload`).
* `client_copy`, the provider behaviour measured against a real store: an unsigned
  `x-amz-copy-source` turns the PUT into a copy from any key in the bucket. The result carries
  the *source's* metadata, so it has no provenance, and whatever digest the request claimed.

Failure injection is explicit and named so a test says what broke.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field


class ClientCannotWrite(Exception):
    """The signed URL does not name this key: the provider answers 403 SignatureDoesNotMatch."""


@dataclass
class MemBucket:
    objects: dict[str, bytes] = field(default_factory=dict)
    #: The keys a ticket was signed for. A client can write these and no others.
    granted: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)
    fail_copy: Exception | None = None
    fail_delete: set[str] = field(default_factory=set)
    #: Runs once, between a copy having been taken and the caller continuing.
    after_copy: Callable[[], None] | None = None
    #: Replaces what the next `head` of the key reports, to model a changed object.
    head_override: dict[str, int | None] = field(default_factory=dict)
    digest: dict[str, str | None] = field(default_factory=dict)
    #: Provenance a key carries when it is not the plain-PUT default (None = a provider copy).
    meta: dict[str, str | None] = field(default_factory=dict)

    # -- the client ---------------------------------------------------------------

    def grant(self, key: str) -> None:
        self.granted.add(key)

    def client_put(self, key: str, body: bytes) -> None:
        """What a ticket holder can do. Anything but a granted key is refused."""
        if key not in self.granted:
            raise ClientCannotWrite(key)
        self.objects[key] = body
        self.meta.pop(key, None)

    def client_copy(self, key: str, source_key: str) -> None:
        """The provider-copy primitive: a PUT to the granted `key` executed as a copy."""
        if key not in self.granted:
            raise ClientCannotWrite(key)
        self.objects[key] = self.objects[source_key]
        self.meta[key] = None

    # -- the finalizer ------------------------------------------------------------

    def head(self, key: str) -> int | None:
        self.calls.append(("head", key))
        if key in self.head_override:
            return self.head_override[key]
        found = self.objects.get(key)
        return None if found is None else len(found)

    def copy(self, source_key: str, dest_key: str) -> None:
        self.calls.append(("copy", f"{source_key}->{dest_key}"))
        if self.fail_copy is not None:
            raise self.fail_copy
        self.objects[dest_key] = self.objects[source_key]
        if self.after_copy is not None:
            hook, self.after_copy = self.after_copy, None
            hook()

    def delete(self, key: str) -> None:
        self.calls.append(("delete", key))
        if key in self.fail_delete:
            raise RuntimeError("the provider refused the delete")
        self.objects.pop(key, None)

    def provenance(self, key: str) -> str | None:
        self.calls.append(("provenance", key))
        if key in self.meta:
            return self.meta[key]
        parts = key.split("/")
        # A plain PUT of a ticket stores its upload id: the segment after `incoming`.
        return parts[5] if len(parts) == 7 and parts[4] == "incoming" else None

    def sha256(self, key: str) -> str | None:
        self.calls.append(("sha256", key))
        found = self.objects.get(key)
        return None if found is None else hashlib.sha256(found).hexdigest()

    def checksum(self, key: str) -> str | None:
        self.calls.append(("checksum", key))
        return self.digest.get(key)
