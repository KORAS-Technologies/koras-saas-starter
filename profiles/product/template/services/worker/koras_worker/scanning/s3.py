"""The S3-compatible `ObjectSource`: read-only, key-only, platform default bucket.

The vendored `koras_storage.ObjectStore` offers a size from `head` and the whole
object from `get`: no ETag, no last-modified, no stream.
This adapter adds exactly those two reads and nothing else, without patching the
vendored package. It issues `HeadObject` and `GetObject` and no other call, so it
cannot write, copy, delete or sign anything.

**The bucket is never chosen by a tenant, a request or a file.** The only
constructor, `default_bucket_source`, resolves the platform default destination
from the product's own settings (`resolve_destination(None, ...)`), which is the
one place the worker can read with the credentials it already holds. A tenant whose objects
live elsewhere is unreadable here, and that fails as a missing object, never as a read from
somewhere else.
"""

from __future__ import annotations

import base64
from typing import Any

from koras_storage import S3ObjectStore, StorageSettings, resolve_destination

from .objects import ObjectIdentity, ObjectSourceError

_NOT_FOUND = frozenset({"404", "NoSuchKey", "NotFound"})


def _error_code(error: Exception) -> str:
    """The provider's error code, without importing botocore's exception types.

    The worker does not declare botocore (it arrives through `koras-storage`),
    and a `ClientError` is recognisable by the `response` it carries. Anything
    without one, a connection failure included, has no code and is "could not
    ask", never "not found".
    """
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return ""
    return str(response.get("Error", {}).get("Code", ""))


def _provider_sha256(value: object) -> str | None:
    """The provider's own SHA-256 as hex, or `None`.

    `None` for anything that is not a full single SHA-256: a multipart object's
    composite checksum is a digest of digests and is not comparable to a digest
    of the bytes. This reads the checksum header only; an ETag never reaches it.
    """
    if not isinstance(value, str) or "-" in value:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return raw.hex() if len(raw) == 32 else None


def _identity(answer: dict[str, Any]) -> ObjectIdentity:
    return ObjectIdentity(
        size=int(answer.get("ContentLength", 0)),
        etag=answer.get("ETag"),
        last_modified=answer.get("LastModified"),
        version_id=answer.get("VersionId"),
        provider_sha256=_provider_sha256(answer.get("ChecksumSHA256")),
    )


class _OpenedS3Object:
    def __init__(self, identity: ObjectIdentity, body: Any) -> None:  # noqa: ANN401 - StreamingBody
        self.identity = identity
        self._body = body

    def read(self, amount: int) -> bytes:
        return bytes(self._body.read(amount))

    def close(self) -> None:
        self._body.close()


class S3ObjectSource:
    """Reads one bucket by key. The bucket and the client are fixed at construction."""

    def __init__(self, client: Any, bucket: str) -> None:  # noqa: ANN401 - a boto3 client
        if not bucket:
            raise ValueError("a bucket is required")
        self._client = client
        self._bucket = bucket

    def stat(self, key: str) -> ObjectIdentity | None:
        try:
            answer = self._client.head_object(Bucket=self._bucket, Key=key, ChecksumMode="ENABLED")
        except Exception as error:  # noqa: BLE001 - every failure to ask is "could not ask"
            if _error_code(error) in _NOT_FOUND:
                return None
            raise ObjectSourceError("the store could not answer the metadata request") from error
        return _identity(answer)

    def open(self, key: str) -> _OpenedS3Object:
        try:
            answer = self._client.get_object(Bucket=self._bucket, Key=key, ChecksumMode="ENABLED")
        except Exception as error:  # noqa: BLE001 - including the object having vanished
            raise ObjectSourceError("the store would not open the object") from error
        return _OpenedS3Object(_identity(answer), answer["Body"])


def default_bucket_source(settings: StorageSettings) -> S3ObjectSource:
    """The reader for the platform default bucket, from the product's own settings.

    Takes no policy, no endpoint and no bucket: those come from `settings`, which
    the worker reads from its environment. `S3ObjectStore` is used for what it is
    for, building the client from a resolved `Destination`; its private client is
    reached here because the public surface has no ETag, last-modified or stream.
    The upstream request for `stat` and streaming is the way to remove this.
    """
    destination = resolve_destination(None, settings)
    store = S3ObjectStore(destination)
    return S3ObjectSource(store._client, destination.bucket)  # noqa: SLF001
