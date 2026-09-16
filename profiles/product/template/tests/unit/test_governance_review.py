"""The defects two independent reviews found, each with the test that would have.

Every assertion here corresponds to something that shipped wrong and was found
by reading rather than by running. That is the point of the file: each one is
cheap, and none of them existed.
"""

from __future__ import annotations

import base64
import inspect
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.routers import audit_exports, files, holds  # noqa: E402
from koras_auth.permissions import OrganizationRole, permissions_for  # noqa: E402
from koras_storage import _hex_digest  # noqa: E402

# -- route order ---------------------------------------------------------------


def _paths(router: object) -> list[str]:
    return [route.path for route in router.routes]  # type: ignore[attr-defined]


def test_the_exports_collection_is_not_shadowed_by_the_single_event_route() -> None:
    """`/audit/exports` and `/audit/{event_id}` are the same shape to Starlette.

    It matches in registration order, so the router carrying `{event_id}` must
    be included after the one carrying `exports`. When it was the other way
    round, every request for the exports list was answered by the single-event
    route as a 404 for an event whose id happened to be the word `exports`.
    """
    from koras_api.routers import audit

    exports = _paths(audit_exports.router)
    assert "/audit/exports" in exports
    # The single-event route exists and is the ambiguous one.
    assert "/audit/{event_id}" in _paths(audit.router)


def test_main_registers_the_exports_router_first() -> None:
    source = (
        inspect.getsourcefile(audit_exports) or ""
    )  # anchor the assertion to the template, not a guess
    assert source.endswith("audit_exports.py")

    from pathlib import Path

    main = Path(source).parent.parent / "main.py"
    text = main.read_text(encoding="utf-8")
    assert text.index("audit_exports.router") < text.index(
        "audit.router"
    ), "the single-event route would shadow /audit/exports"


# -- the export ceiling refuses rather than trims -------------------------------


def test_the_export_asks_for_one_row_more_than_it_will_accept() -> None:
    """A page exactly at the ceiling is indistinguishable from an over-full one
    unless one more row is asked for. Without the `+ 1` the refusal below could
    never fire, and the export silently held the most recent 200,000 rows while
    its own comment promised it never would."""
    source = inspect.getsource(audit_exports.write_export)
    assert "EXPORT_ROW_CEILING + 1" in source
    assert "raise ValueError" in source


def test_a_failed_export_does_not_name_the_provider_exception() -> None:
    """`ClientError`, `NoCredentialsError`, `EndpointConnectionError`: the class
    name is infrastructure fingerprinting, and it was being written into a
    column a customer reads."""
    source = inspect.getsource(audit_exports.write_export)
    assert "type(problem).__name__" not in source


def test_an_export_is_closed_out_by_a_second_event_not_an_update() -> None:
    """`audit_events` carries no update policy. Resolving the `pending` outcome
    by updating the row would touch zero rows and report success."""
    source = inspect.getsource(audit_exports)
    assert "update public.audit_events" not in source
    assert "audit.export_completed" in source


# -- deletion under hold -------------------------------------------------------


def test_deleting_a_file_consults_the_hold() -> None:
    """The hold protected a file from the sweep and not from the person.

    `storage_lifecycle` would not select a held row, so nothing expired it --
    and `DELETE /files/{id}` removed it on request, which is the path an
    insider actually takes.
    """
    source = inspect.getsource(files.delete_file)
    assert "legal_hold" in source
    assert "under_legal_hold" in source
    assert "FILE_UNDER_HOLD" in source


def test_the_delete_audit_detail_no_longer_carries_the_filename() -> None:
    """A filename is content: `2026-redundancies.xlsx` discloses the matter to
    everyone who may read the audit history, which is more people than may
    read the file."""
    source = inspect.getsource(files.delete_file)
    assert '"name"' not in source


# -- checksums that can actually match -----------------------------------------


def test_a_provider_digest_is_read_as_a_digest_and_not_an_etag() -> None:
    """The column takes 64 lowercase hex characters. An ETag is 32, so the
    comparison was structurally incapable of ever matching and integrity read
    as unverified for every object in the estate."""
    raw = bytes(range(32))
    assert _hex_digest(base64.b64encode(raw).decode()) == raw.hex()
    assert len(_hex_digest(base64.b64encode(raw).decode())) == 64


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-base64!!",
        # A composite digest for a multipart upload: the provider's digest of
        # digests, which is not the digest of the object.
        base64.b64encode(bytes(range(32))).decode() + "-4",
        # Sixteen bytes is an MD5, which is what an ETag is.
        base64.b64encode(bytes(range(16))).decode(),
    ],
)
def test_anything_that_is_not_a_sha256_is_refused(value: str) -> None:
    assert _hex_digest(value) is None


# -- the retention override is bounded -----------------------------------------


def test_the_override_ceiling_is_ten_years() -> None:
    assert holds.MAX_RETENTION_DAYS == 3650


def test_every_override_field_carries_the_ceiling() -> None:
    """One field without `le=` is the whole control: a tenant that can set any
    one kind to a million days has made that data undeletable."""
    for name, field in holds.RetentionOverrides.model_fields.items():
        bounds = [m for m in field.metadata if getattr(m, "le", None) is not None]
        assert bounds, f"{name} has no upper bound"
        assert bounds[0].le == holds.MAX_RETENTION_DAYS, name


# -- two people, on the way out as well as in ----------------------------------


def test_lifting_a_hold_refuses_the_person_who_requested_it() -> None:
    source = inspect.getsource(holds.release_hold)
    assert "hold.requested_by == claims.sub" in source
    assert "hold.refused" in source


def test_a_security_administrator_may_request_a_hold() -> None:
    """Until this grant existed, the holds router's owner-or-administrator
    check could never fire: only owners and administrators held the permission
    at all, so a two-tier rule was a one-tier rule with a comment."""
    granted = permissions_for([OrganizationRole.SECURITY_ADMIN])
    assert "audit.legal_hold" in granted
    # And still not the authority to approve or lift one, which the router
    # checks by role rather than by permission.
    assert OrganizationRole.SECURITY_ADMIN not in holds._MANAGERS
