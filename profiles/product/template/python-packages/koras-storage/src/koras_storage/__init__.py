"""Where a tenant's files go, and how the product gets them there.

Two halves. `Destination` is *where*: a provider, a bucket, a region and an
endpoint, resolved from the Control Plane's storage policy for the customer
with the product's own settings as the fallback. `ObjectStore` is *how*: one
S3-compatible client, because Supabase Storage, Cloudflare R2, AWS S3 and the
local MinIO all speak that protocol, and one client with four endpoints is a
smaller surface than four clients.

The product never proxies bytes. A browser uploads straight to the bucket on a
signed URL this package mints, and downloads the same way; the API records the
row and checks the object. Credentials therefore never leave the API, the
browser holds a URL that expires in minutes and names one key, and a file the
size of a video does not pass through a Fly machine.

What is deliberately absent: a provider the policy can name but this cannot
serve. `azure-blob` is not S3-compatible, and `customer-owned` needs the
customer's own credential, which nothing in the estate holds yet. Both resolve
to `Unsupported`, and the API answers 503 with the reason rather than silently
writing the customer's files to the platform default they asked to leave.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

# boto3 ships no type information; the calls below are the four this package
# makes, each wrapped so the rest of the codebase sees typed values.
import boto3  # type: ignore[import-untyped]
from botocore.client import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

__all__ = [
    "CHECKSUM_UNSUPPORTED",
    "INTEGRITY_REFUSED",
    "IntegrityRefused",
    "S3_COMPATIBLE",
    "Category",
    "Destination",
    "ObjectPage",
    "ObjectStore",
    "StoredObject",
    "Provider",
    "S3ObjectStore",
    "StoragePolicy",
    "StorageSettings",
    "Unsupported",
    "object_key",
    "resolve_destination",
    "safe_filename",
]


class Provider(StrEnum):
    """The providers the Control Plane's policy may name. Mirrors its enum."""

    SUPABASE = "supabase"
    CLOUDFLARE_R2 = "cloudflare-r2"
    AWS_S3 = "aws-s3"
    AZURE_BLOB = "azure-blob"
    CUSTOMER_OWNED = "customer-owned"


#: The providers one S3-compatible client can serve.
S3_COMPATIBLE = frozenset({Provider.SUPABASE, Provider.CLOUDFLARE_R2, Provider.AWS_S3})


#: Provider codes meaning "the digest you sent is not the digest of what I
#: received". Never retried without the digest: writing the bytes anyway and
#: calling the result a copy is how a corrupt object becomes a backup.
INTEGRITY_REFUSED = frozenset(
    {"BadDigest", "InvalidDigest", "XAmzContentChecksumMismatch", "ChecksumMismatch"}
)

#: Provider codes meaning "I do not understand that parameter". Retried once
#: without it, because a provider with no SHA-256 support should give a copy
#: nobody could verify rather than no copy at all.
CHECKSUM_UNSUPPORTED = frozenset(
    {"NotImplemented", "InvalidRequest", "InvalidArgument", "BadRequest", "MethodNotAllowed"}
)


class IntegrityRefused(Exception):
    """A provider rejected a write because the bytes did not match the digest.

    Separate from `Unsupported` because the responses are opposite: an
    unsupported parameter is dropped and the write retried, while this is the
    control working and must reach the caller as a failure.
    """


class Unsupported(Exception):
    """The policy names a provider this product cannot write to yet.

    Raised at resolution, before any upload is offered, so the customer sees
    "not available" rather than a file that vanished into the wrong bucket.
    """


@dataclass(frozen=True)
class StoragePolicy:
    """What the Control Plane answered, or nothing.

    `bucket` and `region` may be None: the platform default names neither, and
    a policy for a platform-hosted provider may leave them to the product.
    `config` is the provider's own settings -- an endpoint for R2 -- and never
    a credential; the platform refuses to store one.
    """

    provider: Provider
    bucket: str | None = None
    region: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StorageSettings:
    """The product's own storage settings, from Doppler.

    `endpoint`, `bucket` and the default credential pair serve the platform
    default -- Supabase in a deployed environment, MinIO locally. The optional
    per-provider pairs are for a customer whose policy names R2 or S3 under the
    *product's* account; a customer's own account is `customer-owned` and out
    of scope here.
    """

    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    r2_access_key: str = ""
    r2_secret_key: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""


@dataclass(frozen=True)
class Destination:
    """Everything the client needs to reach one bucket."""

    provider: Provider
    endpoint: str | None
    bucket: str
    region: str
    access_key: str
    secret_key: str


def resolve_destination(policy: StoragePolicy | None, settings: StorageSettings) -> Destination:
    """Turn a policy and the product's settings into somewhere to write.

    The policy decides the provider and may name a bucket and region; the
    product's settings supply whatever the policy left out and the credential
    for the provider. No policy is the platform default, which is exactly what
    the Control Plane answers for a customer nobody has decided anything for.
    """
    provider = policy.provider if policy is not None else Provider.SUPABASE
    if provider not in S3_COMPATIBLE:
        raise Unsupported(f"storage provider {provider.value!r} is not served by this product yet")

    bucket = (policy.bucket if policy is not None else None) or settings.bucket
    region = (policy.region if policy is not None else None) or settings.region
    if not bucket:
        raise Unsupported("no storage bucket is configured for this customer or this product")

    if provider is Provider.SUPABASE:
        return Destination(
            provider, settings.endpoint, bucket, region, settings.access_key, settings.secret_key
        )

    config = policy.config if policy is not None else {}
    endpoint = config.get("endpoint")
    if provider is Provider.CLOUDFLARE_R2:
        if not isinstance(endpoint, str) or not endpoint:
            raise Unsupported("a Cloudflare R2 policy needs an endpoint in its configuration")
        key, secret = settings.r2_access_key, settings.r2_secret_key
    else:
        endpoint = endpoint if isinstance(endpoint, str) and endpoint else None
        key, secret = settings.s3_access_key, settings.s3_secret_key
    if not key or not secret:
        raise Unsupported(
            f"this product holds no credential for {provider.value}; "
            "set the provider's access key pair in Doppler"
        )
    return Destination(provider, endpoint, bucket, region, key, secret)


_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str) -> str:
    """A display name reduced to something a key and a header can carry.

    Path separators, control characters and anything outside a small ASCII
    set are replaced, because the name goes into an object key and into a
    `Content-Disposition` header the provider signs. The original stays in
    the row for display.
    """
    cleaned = _UNSAFE.sub("_", name.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    return cleaned[:180] or "file"


class Category(StrEnum):
    """What an object is for. Mirrors the check constraint on `files.category`.

    A closed set, because it is a path segment: an open one would let a caller
    invent a prefix, and a prefix a caller invents is a prefix a caller can
    aim somewhere else.
    """

    DOCUMENTS = "documents"
    EXPORTS = "exports"
    IMPORTS = "imports"
    ATTACHMENTS = "attachments"
    GENERATED = "generated"
    REPORTS = "reports"
    ARCHIVES = "archives"
    TEMP = "temp"


def object_key(
    tenant_id: str, file_id: str, name: str, *, category: Category = Category.DOCUMENTS
) -> str:
    """tenants/<tenant>/<category>/<file>/<name>: readable back to its owner.

    The tenant is the security boundary and the category is what the object is
    for. Nothing else is in the key: an environment is already a separate
    bucket, a deployment is already one product, and an organization is a fact
    that changes -- a tenant that moved organization would have to have every
    object copied to keep a key honest. A date would freeze a second such fact
    for the sake of a listing nothing performs.

    The category segment arrived on 2026-09-15. Keys written before it have no
    such segment and are not rewritten: `files.storage_key` stores what was
    signed, and rewriting it would unpick every row that holds one.
    """
    return f"tenants/{tenant_id}/{category}/{file_id}/{safe_filename(name)}"


@dataclass(frozen=True)
class StoredObject:
    """One object as the bucket describes it, which is not what the index says.

    The point of listing is to compare the two, so this carries only what a
    bucket can answer for: the key, the size, and the entity tag where the
    provider gives one. It is never a substitute for the row.
    """

    key: str
    size: int
    etag: str | None = None


@dataclass(frozen=True)
class ObjectPage:
    """A page of a listing, and where to continue it.

    Paged rather than whole: a tenant's prefix is unbounded, and a sweep that
    reads all of it into memory is an outage waiting for the largest customer.
    `truncated` says the bucket had more to give, which is not the same as
    `cursor` being set on every provider.
    """

    objects: tuple[StoredObject, ...]
    cursor: str | None = None
    truncated: bool = False


class ObjectStore(Protocol):
    """What the API asks of a bucket. Small on purpose; see the module docstring."""

    def presign_upload(
        self,
        key: str,
        content_type: str,
        size: int,
        expires_in: int,
        checksum_sha256: str | None = None,
    ) -> str: ...

    def presign_download(self, key: str, filename: str, expires_in: int) -> str: ...

    def head(self, key: str) -> int | None:
        """The object's size in bytes, or None when it does not exist."""
        ...

    def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        *,
        checksum_sha256: str | None = None,
    ) -> None:
        """Write an object the API produced itself -- a report export -- in one call.

        Uploads from a browser go through a signed URL and never through
        here; this is for bytes the API already holds.

        `checksum_sha256`, where given, is hex and is sent with the write. The
        provider then verifies what it received before storing it and keeps the
        digest, so a later `checksum()` has something to answer with. A
        provider that refuses because the bytes do not match raises
        `IntegrityRefused`; one that refuses because it does not understand the
        parameter gets the write again without it, and the copy is then one
        nobody can verify rather than no copy at all.
        """
        ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str, *, cursor: str | None = None, limit: int = 1000) -> ObjectPage:
        """What is actually in the bucket under a prefix.

        Added for reconciliation, which two comments in this repository have
        promised since 00005 and which could not be written without it: a row
        without an object and an object without a row are both findable only
        by asking the bucket what it holds. Never exposed to a tenant route --
        the prefix is chosen by the caller, and a caller that can choose a
        prefix can choose another tenant's.
        """
        ...

    def get(self, key: str) -> bytes | None:
        """The stored bytes, or None where the object is not there.

        Used where an object has to pass *through* this process rather than
        between two buckets a single provider can reach -- a cross-provider
        backup is the one caller. Everything else signs a URL and lets the
        browser talk to the provider directly, which is the reason this is not
        the ordinary way to read a file.
        """
        ...

    def copy(self, source_key: str, dest_key: str, *, dest: Destination | None = None) -> None:
        """Copy one object, optionally into another destination.

        Server-side, so the bytes never reach this process. That also means the
        destination's provider must be able to reach the source bucket: a
        `dest` at a different endpoint is a copy no single provider can make,
        and the caller reads the bytes and puts them instead.

        The copy asks the destination to compute a SHA-256 of what it stored,
        so that a later `checksum()` on the copy has something to answer with.
        A provider that ignores the request leaves the copy verifiable only as
        `copied`, which is the honest outcome rather than a failure.

        There is no `move`. Copy and delete at the call site is two events in
        the audit trail and one visible failure in between, where a move is
        one event that either happened or silently half happened.
        """
        ...

    def checksum(self, key: str) -> str | None:
        """The provider's own SHA-256 of the stored bytes, or None.

        None where the provider holds no comparable digest -- which is most
        objects, because a provider only computes one when the upload asked it
        to. It is never an entity tag: an ETag is an MD5 for a single-part
        object and a digest of digests for a multipart one, and comparing
        either to a SHA-256 would report every object as a mismatch.
        """
        ...


class S3ObjectStore:
    """The one client, pointed at whichever endpoint the destination names.

    Path-style addressing throughout: Supabase's S3 gateway and MinIO require
    it, and R2 and S3 accept it. Signature v4, because R2 speaks nothing else.
    """

    def __init__(self, destination: Destination) -> None:
        self.destination = destination
        self._client = boto3.client(
            "s3",
            endpoint_url=destination.endpoint,
            region_name=destination.region,
            aws_access_key_id=destination.access_key,
            aws_secret_access_key=destination.secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_upload(
        self,
        key: str,
        content_type: str,
        size: int,
        expires_in: int,
        checksum_sha256: str | None = None,
    ) -> str:
        # The content type is part of the signature, so the browser must send
        # exactly what the API recorded -- which is what stops a client
        # uploading an HTML file under the name it registered as a PDF.
        #
        # The digest, where the client offered one, is signed too. That is what
        # makes corroboration possible at all: a provider only stores a SHA-256
        # when the upload asked it to, and without it `checksum` has nothing to
        # answer with and every object reads as unverified forever. It also
        # makes the provider reject bytes that do not match the digest, so a
        # corrupted transfer fails at the bucket rather than being recorded as
        # a file whose claim nobody could check.
        params: dict[str, Any] = {
            "Bucket": self.destination.bucket,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
        }
        if checksum_sha256:
            params["ChecksumSHA256"] = _b64_digest(checksum_sha256)
        return str(
            self._client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
        )

    def presign_download(self, key: str, filename: str, expires_in: int) -> str:
        # Downloaded, never rendered in the tab: a file a customer uploaded is
        # not a page this product vouches for.
        disposition = f'attachment; filename="{safe_filename(filename)}"'
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.destination.bucket,
                    "Key": key,
                    "ResponseContentDisposition": disposition,
                },
                ExpiresIn=expires_in,
            )
        )

    def head(self, key: str) -> int | None:
        try:
            answer = self._client.head_object(Bucket=self.destination.bucket, Key=key)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return int(answer.get("ContentLength", 0))

    def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        *,
        checksum_sha256: str | None = None,
    ) -> None:
        arguments: dict[str, Any] = {
            "Bucket": self.destination.bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
        }
        if checksum_sha256 is None:
            self._client.put_object(**arguments)
            return

        arguments["ChecksumSHA256"] = _b64_digest(checksum_sha256)
        try:
            self._client.put_object(**arguments)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in INTEGRITY_REFUSED:
                raise IntegrityRefused(
                    "the destination refused the write: the bytes do not match the digest"
                ) from error
            if code not in CHECKSUM_UNSUPPORTED:
                raise
            # A provider that does not speak SHA-256 checksums. The copy is
            # still worth making; it is simply one nobody can verify, which is
            # what `checksum()` then reports by answering None.
            del arguments["ChecksumSHA256"]
            self._client.put_object(**arguments)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.destination.bucket, Key=key)

    def get(self, key: str) -> bytes | None:
        try:
            answer = self._client.get_object(Bucket=self.destination.bucket, Key=key)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        body = answer["Body"].read()
        return bytes(body)

    def list(self, prefix: str, *, cursor: str | None = None, limit: int = 1000) -> ObjectPage:
        arguments: dict[str, Any] = {
            "Bucket": self.destination.bucket,
            "Prefix": prefix,
            "MaxKeys": limit,
        }
        if cursor:
            arguments["ContinuationToken"] = cursor
        answer = self._client.list_objects_v2(**arguments)
        objects = tuple(
            StoredObject(
                key=str(item["Key"]),
                size=int(item.get("Size", 0)),
                etag=_etag(item.get("ETag")),
            )
            for item in answer.get("Contents", [])
        )
        truncated = bool(answer.get("IsTruncated", False))
        return ObjectPage(
            objects=objects,
            cursor=answer.get("NextContinuationToken") if truncated else None,
            truncated=truncated,
        )

    def copy(self, source_key: str, dest_key: str, *, dest: Destination | None = None) -> None:
        target = dest or self.destination
        client = self._client if dest is None else S3ObjectStore(target)._client
        arguments: dict[str, Any] = {
            "Bucket": target.bucket,
            "Key": dest_key,
            "CopySource": {"Bucket": self.destination.bucket, "Key": source_key},
        }
        try:
            # So the copy carries a digest of its own. Without it S3 stores no
            # SHA-256 for a copied object, `checksum()` on the copy answers
            # None, and a backup could never be more than `copied`.
            client.copy_object(**arguments, ChecksumAlgorithm="SHA256")
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code not in CHECKSUM_UNSUPPORTED:
                raise
            # A gateway that does not implement checksums on copy. Better an
            # unverifiable copy than no copy: the object is still somewhere
            # else, and the catalogue says plainly that nobody compared it.
            client.copy_object(**arguments)

    def checksum(self, key: str) -> str | None:
        try:
            answer = self._client.head_object(
                Bucket=self.destination.bucket, Key=key, ChecksumMode="ENABLED"
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return _hex_digest(answer.get("ChecksumSHA256"))


def _etag(value: object) -> str | None:
    """A provider's entity tag, unquoted, as an opaque marker.

    Useful in a listing to tell two versions of one key apart. **Not a digest
    anybody may compare with a SHA-256**: for a single-part object an ETag is
    an MD5, and for a multipart one it is a digest of digests. `checksum()`
    deliberately does not use this.
    """
    if not isinstance(value, str):
        return None
    return value.strip('"') or None


def _b64_digest(hex_digest: str) -> str:
    """A hex SHA-256 as the base64 the S3 protocol carries."""
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def _hex_digest(value: object) -> str | None:
    """A provider's base64 SHA-256 as hex, or None.

    None rather than a guess for anything that is not a full SHA-256: a
    multipart object's composite checksum carries a `-<parts>` suffix and is a
    digest of digests, which cannot be compared with a digest of the bytes.
    Returning it would turn "cannot verify" into "does not match", and every
    large object would read as corrupt.

    This read an ETag until 2026-09-16, which could never match a SHA-256 at
    all -- an ETag is 32 hex characters and a SHA-256 is 64 -- so the
    verification it fed was structurally incapable of succeeding. A review
    found it.
    """
    if not isinstance(value, str) or "-" in value:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return raw.hex() if len(raw) == 32 else None
