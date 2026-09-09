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
    "Destination",
    "ObjectStore",
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


def object_key(tenant_id: str, file_id: str, name: str) -> str:
    """tenants/<tenant>/<file>/<name>: readable back to its owner, never colliding."""
    return f"tenants/{tenant_id}/{file_id}/{safe_filename(name)}"


class ObjectStore(Protocol):
    """What the API asks of a bucket. Small on purpose; see the module docstring."""

    def presign_upload(self, key: str, content_type: str, size: int, expires_in: int) -> str: ...

    def presign_download(self, key: str, filename: str, expires_in: int) -> str: ...

    def head(self, key: str) -> int | None:
        """The object's size in bytes, or None when it does not exist."""
        ...

    def delete(self, key: str) -> None: ...


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

    def presign_upload(self, key: str, content_type: str, size: int, expires_in: int) -> str:
        # The content type is part of the signature, so the browser must send
        # exactly what the API recorded -- which is what stops a client
        # uploading an HTML file under the name it registered as a PDF.
        return str(
            self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.destination.bucket,
                    "Key": key,
                    "ContentType": content_type,
                    "ContentLength": size,
                },
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

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.destination.bucket, Key=key)
