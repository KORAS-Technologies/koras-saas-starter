"""The storage package, without a bucket.

Resolution is the half worth testing here: which provider, which bucket,
which credential, and which policies are refused before an upload is ever
offered. The client itself is boto3 with an endpoint, and its signing is
exercised only as far as "produces a URL naming the right bucket and key" --
the provider's acceptance of that signature is what the local MinIO stack and
the deployed smoke check are for.
"""

from __future__ import annotations

import base64
from urllib.parse import urlparse

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from koras_storage import (
    CHECKSUM_UNSUPPORTED,
    INTEGRITY_REFUSED,
    Category,
    Destination,
    IntegrityRefused,
    ObjectPage,
    Provider,
    S3ObjectStore,
    StoragePolicy,
    StorageSettings,
    Unsupported,
    object_key,
    resolve_destination,
    safe_filename,
)

SETTINGS = StorageSettings(
    endpoint="http://localhost:9000",
    bucket="local-dev",
    region="us-east-1",
    access_key="minio",
    secret_key="miniominio",  # noqa: S106 - a local stack default, not a credential
    r2_access_key="r2-key",
    r2_secret_key="r2-secret",  # noqa: S106
)


def test_no_policy_is_the_platform_default() -> None:
    destination = resolve_destination(None, SETTINGS)
    assert destination.provider is Provider.SUPABASE
    assert destination.endpoint == "http://localhost:9000"
    assert destination.bucket == "local-dev"
    assert destination.access_key == "minio"


def test_a_supabase_policy_may_name_its_own_bucket_and_region() -> None:
    policy = StoragePolicy(Provider.SUPABASE, bucket="acme-files", region="eu-central-1")
    destination = resolve_destination(policy, SETTINGS)
    assert destination.bucket == "acme-files"
    assert destination.region == "eu-central-1"
    # Still the product's own endpoint and credential: it is the product's Supabase.
    assert destination.endpoint == SETTINGS.endpoint
    assert destination.secret_key == SETTINGS.secret_key


def test_r2_needs_an_endpoint_and_uses_its_own_credential() -> None:
    policy = StoragePolicy(
        Provider.CLOUDFLARE_R2,
        bucket="acme",
        config={"endpoint": "https://abc.r2.cloudflarestorage.com"},
    )
    destination = resolve_destination(policy, SETTINGS)
    assert destination.endpoint == "https://abc.r2.cloudflarestorage.com"
    assert destination.access_key == "r2-key"
    # R2 is region-less; boto still wants a name, and "auto" is what it documents.
    assert destination.region == "us-east-1"

    with pytest.raises(Unsupported):
        resolve_destination(StoragePolicy(Provider.CLOUDFLARE_R2, bucket="acme"), SETTINGS)


def test_a_provider_with_no_credential_is_refused_not_defaulted() -> None:
    """The one outcome worse than "not available" is the platform bucket."""
    policy = StoragePolicy(Provider.AWS_S3, bucket="acme", region="eu-west-1")
    with pytest.raises(Unsupported, match="no credential"):
        resolve_destination(policy, SETTINGS)


@pytest.mark.parametrize("provider", [Provider.AZURE_BLOB, Provider.CUSTOMER_OWNED])
def test_providers_this_product_cannot_serve_are_refused(provider: Provider) -> None:
    with pytest.raises(Unsupported):
        resolve_destination(StoragePolicy(provider, bucket="x"), SETTINGS)


def test_a_bucketless_customer_target_is_refused() -> None:
    bare = StorageSettings(
        endpoint="http://x",
        bucket="",
        region="r",
        access_key="a",
        secret_key="b",  # noqa: S106
    )
    with pytest.raises(Unsupported, match="bucket"):
        resolve_destination(None, bare)


def test_filenames_are_reduced_to_something_a_key_and_a_header_can_carry() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("Q3 report (final).pdf") == "Q3 report _final_.pdf"
    assert safe_filename('a"b\r\n.txt') == "a_b_.txt"
    assert safe_filename("...") == "file"
    assert len(safe_filename("x" * 400)) == 180


def test_keys_are_readable_back_to_their_owner() -> None:
    key = object_key("tenant-1", "file-9", "contract.pdf")
    assert key == "tenants/tenant-1/documents/file-9/contract.pdf"


def test_the_export_layout_is_unchanged_by_going_through_one_builder() -> None:
    """The reporting router spelled this by hand until 2026-09-15. The point of
    moving it here is that the bytes do not change; only the second copy goes."""
    assert (
        object_key("tenant-1", "exp-3", "sales.csv", category=Category.EXPORTS)
        == "tenants/tenant-1/exports/exp-3/sales.csv"
    )


def test_a_key_carries_the_tenant_and_the_category_and_nothing_else() -> None:
    """No environment, no organization, no product, no date. Each is either
    already implied by the bucket or a fact that changes after the key is
    signed, and a key is not a place to store a fact that changes."""
    key = object_key("tenant-1", "file-9", "a.pdf", category=Category.ATTACHMENTS)
    assert key.split("/") == ["tenants", "tenant-1", "attachments", "file-9", "a.pdf"]


def test_a_name_that_tries_to_leave_its_prefix_cannot() -> None:
    key = object_key("tenant-1", "file-9", "../../other/evil.pdf")
    assert key == "tenants/tenant-1/documents/file-9/evil.pdf"


def test_signed_urls_name_the_bucket_and_key_and_nothing_else_secret() -> None:
    destination = Destination(
        Provider.SUPABASE, "http://localhost:9000", "local-dev", "us-east-1", "k", "s"
    )
    store = S3ObjectStore(destination)
    upload = store.presign_upload("tenants/t/f/a.pdf", "application/pdf", 12, 300)
    parsed = urlparse(upload)
    assert parsed.path == "/local-dev/tenants/t/f/a.pdf"
    assert "X-Amz-Signature=" in parsed.query
    assert "s" not in parsed.query.split("X-Amz-Credential=")[1].split("&")[0].split("%2F")[0][1:]

    download = store.presign_download("tenants/t/f/a.pdf", 'we"ird.pdf', 300)
    assert "response-content-disposition=" in download
    assert "we_ird.pdf" in download


# ── listing, copying and digests ───────────────────────────────────────────────
#
# The bucket is a stub. What is worth asserting without one is the shape the
# API is handed back and, above all, which entity tags are refused: a digest
# that cannot be compared must be reported as absent, never as a mismatch.


class _Client:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, object]] = []
        self.copies: list[dict[str, object]] = []

    def list_objects_v2(self, **arguments: object) -> dict[str, object]:
        self.calls.append(arguments)
        return self._pages[len(self.calls) - 1]

    def copy_object(self, **arguments: object) -> None:
        self.copies.append(arguments)

    def head_object(self, **arguments: object) -> dict[str, object]:
        self.calls.append(arguments)
        answer: dict[str, object] = {"ETag": self._pages[0].get("ETag", '"abc"')}
        # Only when the object was stored with one. A provider answering an
        # ETag alone is a provider that cannot corroborate a digest, and the
        # store must say so rather than return the ETag.
        if "ChecksumSHA256" in self._pages[0]:
            answer["ChecksumSHA256"] = self._pages[0]["ChecksumSHA256"]
        return answer


def _store(client: _Client) -> S3ObjectStore:
    store = S3ObjectStore(
        Destination(Provider.SUPABASE, "http://localhost:9000", "local-dev", "us-east-1", "k", "s")
    )
    store._client = client
    return store


def test_a_listing_is_paged_and_says_when_there_is_more() -> None:
    client = _Client(
        [
            {
                "Contents": [
                    {"Key": "tenants/t/documents/a/one.pdf", "Size": 10, "ETag": '"aaa"'},
                    {"Key": "tenants/t/documents/b/two.pdf", "Size": 20, "ETag": '"bbb"'},
                ],
                "IsTruncated": True,
                "NextContinuationToken": "next-page",
            }
        ]
    )
    page = _store(client).list("tenants/t/", limit=2)
    assert isinstance(page, ObjectPage)
    assert [item.key for item in page.objects] == [
        "tenants/t/documents/a/one.pdf",
        "tenants/t/documents/b/two.pdf",
    ]
    assert page.objects[0].size == 10
    assert page.truncated is True
    assert page.cursor == "next-page"
    assert client.calls[0]["Prefix"] == "tenants/t/"
    assert client.calls[0]["MaxKeys"] == 2
    assert "ContinuationToken" not in client.calls[0]


def test_a_finished_listing_offers_no_cursor() -> None:
    client = _Client([{"Contents": [], "IsTruncated": False, "NextContinuationToken": "ignored"}])
    page = _store(client).list("tenants/t/", cursor="carry-on")
    assert page.objects == ()
    assert page.truncated is False
    assert page.cursor is None
    assert client.calls[0]["ContinuationToken"] == "carry-on"


def test_a_multipart_composite_checksum_is_absent_rather_than_wrong() -> None:
    """`-2` means a digest of digests. Comparing it to a file's SHA-256 would
    report every large object as corrupt, so it is reported as no digest."""
    digest = base64.b64encode(bytes(range(32))).decode() + "-2"
    client = _Client([{"ChecksumSHA256": digest}])
    assert _store(client).checksum("tenants/t/documents/a/one.pdf") is None


def test_a_provider_digest_is_returned_as_hex() -> None:
    """The column takes 64 lowercase hex characters, and the protocol carries
    base64, so the store converts rather than the caller."""
    raw = bytes(range(32))
    client = _Client([{"ChecksumSHA256": base64.b64encode(raw).decode()}])
    assert _store(client).checksum("tenants/t/documents/a/one.pdf") == raw.hex()


def test_a_head_asks_the_provider_to_return_its_checksum() -> None:
    """Without `ChecksumMode`, S3 omits the field entirely and every object
    reads as having no digest."""
    client = _Client([{"ChecksumSHA256": base64.b64encode(bytes(32)).decode()}])
    _store(client).checksum("tenants/t/documents/a/one.pdf")
    assert client.calls[0]["ChecksumMode"] == "ENABLED"


def test_an_entity_tag_is_never_offered_as_a_checksum() -> None:
    """An ETag is 32 hex characters and a SHA-256 is 64, so the comparison the
    file index performs could never have succeeded. It did exactly this until
    2026-09-16: integrity read as unverified for every object in the estate."""
    client = _Client([{"ETag": '"d41d8cd98f00b204e9800998ecf8427e"'}])
    assert _store(client).checksum("tenants/t/documents/a/one.pdf") is None


def test_a_copy_within_one_destination_names_both_ends() -> None:
    client = _Client([{}])
    _store(client).copy("tenants/t/documents/a/one.pdf", "archives/t/one.pdf")
    assert client.copies[0]["Bucket"] == "local-dev"
    assert client.copies[0]["Key"] == "archives/t/one.pdf"
    assert client.copies[0]["CopySource"] == {
        "Bucket": "local-dev",
        "Key": "tenants/t/documents/a/one.pdf",
    }


# -- a write that carries its own digest ---------------------------------------
#
# The strongest form of the copy: the provider compares before it stores, so a
# corrupt object is refused at the door rather than catalogued and compared
# afterwards. The two failure directions are opposite and must not be confused.


class _WriteClient:
    """A destination that can refuse a write, for one of two reasons."""

    def __init__(self, code: str | None = None) -> None:
        self._code = code
        self.calls: list[dict[str, object]] = []

    def put_object(self, **arguments: object) -> dict[str, object]:
        self.calls.append(arguments)
        if self._code and len(self.calls) == 1:
            raise ClientError({"Error": {"Code": self._code}}, "PutObject")
        return {}


def _write_store(client: _WriteClient) -> S3ObjectStore:
    store = S3ObjectStore(
        Destination(Provider.SUPABASE, "http://localhost:9000", "local-dev", "us-east-1", "k", "s")
    )
    store._client = client
    return store


def test_a_digest_is_sent_with_the_write_as_base64() -> None:
    """The protocol carries base64 and the column holds hex, so the store
    converts. A provider handed hex stores a digest that matches nothing."""
    client = _WriteClient()
    digest = bytes(range(32)).hex()
    _write_store(client).put("k", b"bytes", "text/plain", checksum_sha256=digest)
    assert client.calls[0]["ChecksumSHA256"] == base64.b64encode(bytes(range(32))).decode()


def test_a_write_with_no_digest_sends_no_checksum_at_all() -> None:
    client = _WriteClient()
    _write_store(client).put("k", b"bytes", "text/plain")
    assert "ChecksumSHA256" not in client.calls[0]


@pytest.mark.parametrize("code", sorted(CHECKSUM_UNSUPPORTED))
def test_a_provider_that_cannot_verify_still_receives_the_object(code: str) -> None:
    """Better an unverifiable copy than no copy. The object is still somewhere
    else, and `checksum()` answering None is what reports it unverified."""
    client = _WriteClient(code)
    _write_store(client).put("k", b"bytes", "text/plain", checksum_sha256=bytes(32).hex())
    assert len(client.calls) == 2
    assert "ChecksumSHA256" not in client.calls[1]


@pytest.mark.parametrize("code", sorted(INTEGRITY_REFUSED))
def test_a_provider_that_compared_and_disagreed_is_never_retried(code: str) -> None:
    """The opposite direction, and the one that matters. Retrying without the
    digest would write the bytes anyway and call the result a backup, turning
    a caught corruption into a catalogued one."""
    client = _WriteClient(code)
    with pytest.raises(IntegrityRefused):
        _write_store(client).put("k", b"bytes", "text/plain", checksum_sha256=bytes(32).hex())
    assert len(client.calls) == 1


def test_any_other_refusal_reaches_the_caller_unchanged() -> None:
    """A missing bucket or a rejected credential is neither of the two cases
    above, and swallowing it would make a broken destination look like a
    provider without checksum support."""
    client = _WriteClient("AccessDenied")
    with pytest.raises(ClientError):
        _write_store(client).put("k", b"bytes", "text/plain", checksum_sha256=bytes(32).hex())
    assert len(client.calls) == 1
