"""The storage package, without a bucket.

Resolution is the half worth testing here: which provider, which bucket,
which credential, and which policies are refused before an upload is ever
offered. The client itself is boto3 with an endpoint, and its signing is
exercised only as far as "produces a URL naming the right bucket and key" --
the provider's acceptance of that signature is what the local MinIO stack and
the deployed smoke check are for.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from koras_storage import (
    Destination,
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
    assert key == "tenants/tenant-1/file-9/contract.pdf"


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
