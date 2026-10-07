"""A scripted session, a recording store and a client for the Files routes' release tests.

Nothing here reads a database or a bucket. The row the helpers build is a file as a product
with `secure_files` holds a released one -- a final key of its own tenant and the etag the
scanner stamped -- so that the same row also exercises the legacy route, which ignores both.
The two modes decide differently about the same row, and that is what the tests built on this
module assert (`test_files_release_api.py`).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core import audit as core_audit  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.database import get_db  # noqa: E402
from koras_api.core.storage import StorageGrant, TenantStorage, tenant_storage  # noqa: E402
from koras_api.core.tenant import require_tenant  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_storage import Provider  # noqa: E402
from koras_tenant import TenantContext  # noqa: E402

app.state.redis = None

TENANT = "00000000-0000-0000-0000-00000000000a"
OTHER_TENANT = "00000000-0000-0000-0000-00000000000b"
FILE_ID = "11111111-1111-1111-1111-111111111111"
GENERATION = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
SIGNATURE = "Eicar-Signature"


def final_key(tenant: str = TENANT) -> str:
    return f"tenants/{tenant}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"


class Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:  # noqa: ANN401
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def scalar_one(self) -> int:
        return 0


class Session:
    """Serves `public.files` rows by tenant and id and records everything else."""

    def __init__(self, files: list[SimpleNamespace]) -> None:
        self.files = files
        self.audit: list[dict[str, Any]] = []
        self.statements: list[str] = []
        self.sent: list[Any] = []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Rows:
        sql = str(statement)
        self.statements.append(sql)
        parameters = parameters or {}
        self.sent.append(parameters)
        if "insert into public.audit_events" in sql:
            self.audit.append(parameters)
            return Rows([])
        if "from public.files" in sql and "sum(" not in sql:
            wanted_tenant = parameters.get("tenant_id")
            matched = [
                f
                for f in self.files
                # The tenant the statement names, never the one the row claims for itself.
                if f.owner == wanted_tenant
                and (parameters.get("id") in (None, f.id))
                and ("status = 'ready'" not in sql or f.status == "ready")
                and ("status = :state" not in sql or f.status == parameters.get("state"))
            ]
            return Rows(matched)
        return Rows([])

    async def commit(self) -> None:
        return None


class Store:
    def __init__(self) -> None:
        self.signed: list[str] = []
        self.read: list[str] = []
        self.content: bytes | None = b"%PDF-1.4 hello"

    def head(self, key: str) -> int:
        return 12

    def checksum(self, key: str) -> None:
        return None

    def get(self, key: str) -> bytes | None:
        self.read.append(key)
        return self.content

    def presign_download(self, key: str, filename: str, expires_in: int) -> str:
        self.signed.append(key)
        return f"https://bucket.invalid/{key}?sig=abc"


def file_row(
    scan_status: Any,  # noqa: ANN401
    *,
    status: str = "ready",
    tenant: str = TENANT,
    owner: str | None = None,
    key: str | None = None,
    etag: str | None = "etag-1",
    row_tenant: str | None = None,
) -> SimpleNamespace:
    """One file row.

    `tenant` is the tenant the row belongs to (and whose prefix its key carries); `owner` is
    the tenant a statement must name to find it, which is `tenant` unless a test says
    otherwise; `row_tenant` is what the row's own `tenant_id` column reports, which is
    `tenant` unless a test forges it.
    """
    return SimpleNamespace(
        id=FILE_ID,
        owner=owner or tenant,
        tenant_id=row_tenant or tenant,
        storage_key=key or final_key(tenant),
        name="a.pdf",
        size_bytes=12,
        content_type="application/pdf",
        uploaded_by="user-1",
        uploaded_at=NOW,
        ready_at=NOW,
        scan_status=scan_status,
        scan_object_etag=etag,
        status=status,
        legal_hold=False,
        created_at=NOW,
        indexed_at=None,
        index_note=None,
        checksum_sha256="ab" * 32,
    )


def client(session: Session, store: Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def rebind(bound: object, tenant_id: str) -> None:
        return None

    monkeypatch.setattr(core_audit, "rebind_tenant", rebind)

    def claims() -> JWTClaims:
        return JWTClaims(
            sub="user-1", roles=frozenset({OrganizationRole.MEMBER}), organization_id="org-a"
        )

    def resolved() -> TenantContext:
        return TenantContext(
            id=TENANT, slug="a", name="A", organization_id="org-a", user_id="user-1"
        )

    async def db() -> AsyncIterator[Session]:
        yield session

    def storage() -> TenantStorage:
        return TenantStorage(
            store=store,  # type: ignore[arg-type]
            provider=Provider.AWS_S3,
            bucket="b",
            grant=StorageGrant(enabled=True, limit_bytes=None, resolved=True),
        )

    app.dependency_overrides[require_auth] = claims
    app.dependency_overrides[require_tenant] = resolved
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[tenant_storage] = storage
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def code(answer: Any) -> str:  # noqa: ANN401
    return str(answer.json()["detail"]["code"])
