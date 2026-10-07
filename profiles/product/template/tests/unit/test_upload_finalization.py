"""The shape and the boundaries of immutable upload finalization (ADR 0013, `secure_files`).

What is asserted without a database or a bucket: the two key shapes and how they fail, that the
only key the API ever signs an upload for is an incoming one, that confirming an upload does not
vouch for bytes a ticket can still replace, that the claim is bound once and never invented, that
a confirmed upload is handed to the finalizer and to nothing else, and that nothing in the API
can name a final key. The behaviour against a real PostgreSQL is
`tests/integration/test_upload_finalization_real.py`, and against a real provider
`tests/integration/test_upload_finalization_provider.py`.

This file is generated only into a product with the capability, because the router it drives
issues the secure ticket only there. The other mode's contract is
`tests/unit/test_upload_ticket_contract.py`, which is generated into both.
"""

from __future__ import annotations

import ast
import base64
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core import audit as core_audit  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.database import get_db  # noqa: E402
from koras_api.core.finalize_jobs import (  # noqa: E402
    FILE_FINALIZE,
    PAYLOAD_KEY,
    finalize_idempotency_key,
    finalize_payload,
)
from koras_api.core.jobs import job_queue  # noqa: E402
from koras_api.core.storage import StorageGrant, TenantStorage, tenant_storage  # noqa: E402
from koras_api.core.tenant import require_tenant  # noqa: E402
from koras_api.core.upload_window import (  # noqa: E402
    FINAL,
    FINALIZE_DELAY_SECONDS,
    INCOMING,
    final_key_for,
    incoming_key,
    is_incoming_key,
)
from koras_api.main import app  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_queue import Enqueued  # noqa: E402
from koras_storage import Provider  # noqa: E402
from koras_tenant import TenantContext  # noqa: E402

app.state.redis = None
REPO = Path(__file__).resolve().parents[2]
TENANT_A = "00000000-0000-0000-0000-00000000000a"
FILE_A = "11111111-1111-1111-1111-111111111111"
UPLOAD = "22222222-2222-2222-2222-222222222222"
GENERATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DIGEST = "ab" * 32


# --- the two shapes ---------------------------------------------------------------------


def test_an_incoming_key_has_the_documented_shape_and_no_space() -> None:
    key = incoming_key(TENANT_A, "documents", FILE_A, UPLOAD, "My Report 2025.pdf")
    assert key == f"tenants/{TENANT_A}/documents/{FILE_A}/{INCOMING}/{UPLOAD}/My_Report_2025.pdf"
    assert " " not in key, "Supabase refuses CopyObject for a key with a space"
    assert is_incoming_key(key)


def test_the_final_key_for_an_incoming_one_is_the_documented_shape() -> None:
    key = incoming_key(TENANT_A, "documents", FILE_A, UPLOAD, "a.pdf")
    final = final_key_for(key, GENERATION)
    assert final == f"tenants/{TENANT_A}/documents/{FILE_A}/{FINAL}/{GENERATION}/a.pdf"
    assert not is_incoming_key(final)


@pytest.mark.parametrize(
    "bad",
    [
        f"tenants/{TENANT_A}/documents/{FILE_A}/a.pdf",  # a key written before the capability
        f"tenants/{TENANT_A}/{FILE_A}/a.pdf",
        f"tenants/{TENANT_A}/documents/{FILE_A}/final/{GENERATION}/a.pdf",
        f"tenants/{TENANT_A}/documents/{FILE_A}/incoming/a.pdf",  # not the whole shape
        f"other/{TENANT_A}/documents/{FILE_A}/incoming/{UPLOAD}/a.pdf",
    ],
)
def test_a_final_key_is_made_from_an_incoming_key_and_from_nothing_else(bad: str) -> None:
    with pytest.raises(ValueError):
        final_key_for(bad, GENERATION)


def test_a_generation_must_be_a_canonical_uuid() -> None:
    key = incoming_key(TENANT_A, "documents", FILE_A, UPLOAD, "a.pdf")
    for bad in ("", "not-a-uuid", GENERATION.upper(), "../x"):
        with pytest.raises(ValueError):
            final_key_for(key, bad)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (f"tenants/{TENANT_A}/documents/{FILE_A}/incoming/{UPLOAD}/a.pdf", True),
        # Fails closed: an `incoming` directory anywhere is refused, not argued about.
        (f"tenants/{TENANT_A}/incoming/{FILE_A}/a.pdf", True),
        (f"tenants/{TENANT_A}/documents/{FILE_A}/incoming/x/y/z/a.pdf", True),
        # A file *named* incoming is a file, not a directory; legacy and final shapes are not.
        (f"tenants/{TENANT_A}/documents/{FILE_A}/incoming", False),
        (f"tenants/{TENANT_A}/documents/{FILE_A}/a.pdf", False),
        (f"tenants/{TENANT_A}/documents/{FILE_A}/final/{GENERATION}/a.pdf", False),
    ],
)
def test_is_incoming_fails_closed_on_any_directory_segment(key: str, expected: bool) -> None:
    assert is_incoming_key(key) is expected


def test_the_inputs_of_an_incoming_key_are_validated() -> None:
    for kwargs in (
        {"tenant_id": "x"},
        {"file_id": "x"},
        {"upload_id": "x"},
        {"category": "a/b"},
        {"safe_name": "a/b"},
        {"safe_name": ".."},
    ):
        args = {
            "tenant_id": TENANT_A,
            "category": "documents",
            "file_id": FILE_A,
            "upload_id": UPLOAD,
            "safe_name": "a.pdf",
            **kwargs,
        }
        with pytest.raises(ValueError):
            incoming_key(**args)


# --- the API signs an incoming key, and only that --------------------------------------------


class _Rows:
    def first(self) -> Any:  # noqa: ANN401
        return None

    def fetchall(self) -> list[Any]:
        return []

    def scalar_one(self) -> int:
        return 0


class _Session:
    def __init__(self, pending: SimpleNamespace | None = None) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.pending = pending

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        sql = str(statement)
        parameters = parameters or {}
        if "insert into public.files" in sql:
            self.inserted.append(parameters)
        if sql.startswith("update public.files"):
            self.updates.append((sql, parameters))
        if "from public.files" in sql and self.pending is not None and "id = :id" in sql:
            rows = _Rows()
            rows.first = lambda: self.pending  # type: ignore[method-assign]
            return rows
        return _Rows()

    async def commit(self) -> None:
        return None


class _Store:
    def __init__(self, size: int = 12, digest: str | None = None) -> None:
        self.presigned: list[str] = []
        self.downloads: list[str] = []
        self.size = size
        self.digest = digest
        self.checksum_asked: list[str] = []
        self.provenance: list[str | None] = []
        self.claims: list[str | None] = []

    def presign_upload(
        self,
        key: str,
        content_type: str,
        size: int,
        expires_in: int,
        checksum: str | None = None,
        *,
        provenance: str | None = None,
    ) -> str:
        self.presigned.append(key)
        self.provenance.append(provenance)
        self.claims.append(checksum)
        return f"https://bucket.invalid/{key}?sig=1"

    def presign_download(self, key: str, name: str, expires_in: int) -> str:
        self.downloads.append(key)
        return f"https://bucket.invalid/{key}?download=1"

    def head(self, key: str) -> int:
        return self.size

    def checksum(self, key: str) -> str | None:
        self.checksum_asked.append(key)
        return self.digest


class _Jobs:
    """Records what was enqueued, with the delay a real queue would be given."""

    simulated = False

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, task: Any, **kwargs: Any) -> Enqueued:  # noqa: ANN401
        self.jobs.append({"task": task, **kwargs})
        return Enqueued(task=task.name, job_id="recorded", simulated=False)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clean_overrides() -> Any:  # noqa: ANN401
    yield
    app.dependency_overrides.clear()


def _client(
    session: _Session,
    store: _Store,
    monkeypatch: pytest.MonkeyPatch,
    jobs: _Jobs | None = None,
) -> TestClient:
    async def rebind(bound: object, tenant_id: str) -> None:
        return None

    monkeypatch.setattr(core_audit, "rebind_tenant", rebind)

    async def db() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[require_auth] = lambda: JWTClaims(
        sub="user-1", roles=frozenset({OrganizationRole.MEMBER}), organization_id="org-a"
    )
    app.dependency_overrides[require_tenant] = lambda: TenantContext(
        id=TENANT_A, slug="a", name="A", organization_id="org-a", user_id="user-1"
    )
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[tenant_storage] = lambda: TenantStorage(
        store=store,  # type: ignore[arg-type]
        provider=Provider.AWS_S3,
        bucket="b",
        grant=StorageGrant(enabled=True, limit_bytes=None, resolved=True),
    )
    app.dependency_overrides[job_queue] = lambda: jobs or _Jobs()
    return TestClient(app)


def test_a_ticket_is_signed_for_an_incoming_key_and_the_row_records_the_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, store = _Session(), _Store()
    answer = _client(session, store, monkeypatch).post(
        "/api/v1/files/uploads",
        json={
            "name": "Quarterly Report.pdf",
            "size_bytes": 12,
            "category": "documents",
            "checksum_sha256": DIGEST,
        },
    )
    assert answer.status_code == 201, answer.text
    (signed,) = store.presigned
    (row,) = session.inserted
    assert row["key"] == signed, "the row and the signature name one key"
    assert is_incoming_key(signed) and f"/{INCOMING}/" in signed
    assert f"/{FINAL}/" not in signed and " " not in signed
    assert signed.startswith(f"tenants/{TENANT_A}/documents/{answer.json()['file_id']}/incoming/")
    # The person's own name is kept on the row; only the key is made copy-safe.
    assert row["name"] == "Quarterly Report.pdf"


def test_two_tickets_for_one_name_are_two_incoming_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store = _Session(), _Store()
    client = _client(session, store, monkeypatch)
    for _ in range(2):
        client.post(
            "/api/v1/files/uploads",
            json={
                "name": "a.pdf",
                "size_bytes": 12,
                "category": "documents",
                "checksum_sha256": DIGEST,
            },
        )
    assert len(set(store.presigned)) == 2


def _pending(checksum: str | None, *, key: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=FILE_A,
        tenant_id=TENANT_A,
        storage_key=key or incoming_key(TENANT_A, "documents", FILE_A, UPLOAD, "a.pdf"),
        name="a.pdf",
        size_bytes=12,
        content_type="application/pdf",
        uploaded_by="user-1",
        uploaded_at=datetime(2026, 10, 6, tzinfo=UTC),
        ready_at=None,
        scan_status="pending",
        status="pending",
        legal_hold=False,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        indexed_at=None,
        index_note=None,
        checksum_sha256=checksum,
    )


def test_confirming_an_upload_does_not_vouch_for_the_incoming_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, store = _Session(_pending(DIGEST)), _Store(size=12, digest=DIGEST)
    answer = _client(session, store, monkeypatch).post(
        f"/api/v1/files/{FILE_A}/complete", json={"checksum_sha256": DIGEST}
    )
    assert answer.status_code == 200, answer.text
    # The provider's digest of an object a ticket can still replace is never asked for here...
    assert store.checksum_asked == []
    # ...and the claim bound at issuance is not written again: the update names no checksum
    # column, so nothing the client says now can change it.
    ((sql, params), *_) = [u for u in session.updates if "status = 'ready'" in u[0]]
    assert "checksum" not in sql and "checksum" not in params
    assert answer.json()["checksum_verified"] is False
    assert answer.json()["checksum_sha256"] == DIGEST


def test_confirming_an_upload_signs_nothing_and_hands_nothing_to_a_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A signed URL is a read capability, and the bytes at an incoming key are unverified."""
    session, store = _Session(_pending(DIGEST)), _Store(size=12)
    answer = _client(session, store, monkeypatch).post(f"/api/v1/files/{FILE_A}/complete", json={})
    assert answer.status_code == 200, answer.text
    assert store.downloads == []


def test_confirming_an_upload_hands_it_to_the_finalizer_after_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = _Jobs()
    pending = _pending(DIGEST)
    pending.created_at = datetime.now(UTC)  # a ticket issued just now
    session = _Session(pending)
    answer = _client(session, _Store(size=12), monkeypatch, jobs).post(
        f"/api/v1/files/{FILE_A}/complete", json={}
    )
    assert answer.status_code == 200, answer.text
    (job,) = jobs.jobs
    assert job["task"] is FILE_FINALIZE
    assert job["tenant_id"] == TENANT_A
    assert job["payload"] == {PAYLOAD_KEY: FILE_A} == finalize_payload(FILE_A)
    assert job["idempotency_key"] == finalize_idempotency_key(FILE_A)
    # Deferred to the end of the window: never before the ticket and any request it began
    # are certainly dead. A few seconds of slack for the test's own clock.
    assert FINALIZE_DELAY_SECONDS - 30 <= job["delay_seconds"] <= FINALIZE_DELAY_SECONDS + 30


def test_a_job_that_cannot_be_enqueued_leaves_the_upload_confirmed_and_unreleased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Broken(_Jobs):
        async def enqueue(self, task: Any, **kwargs: Any) -> Enqueued:  # noqa: ANN401
            raise ConnectionError("the queue is down")

    pending = _pending(DIGEST)
    session = _Session(pending)
    answer = _client(session, _Store(size=12), monkeypatch, _Broken()).post(
        f"/api/v1/files/{FILE_A}/complete", json={}
    )
    # The upload is the customer's and it succeeded; the sweep owns the recovery. What it is
    # not is releasable: its key is still an incoming one, which the download refuses below.
    assert answer.status_code == 200, answer.text
    assert is_incoming_key(pending.storage_key)


def test_the_client_cannot_change_the_claim_at_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_pending(DIGEST))
    answer = _client(session, _Store(size=12), monkeypatch).post(
        f"/api/v1/files/{FILE_A}/complete", json={"checksum_sha256": "cd" * 32}
    )
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] == "upload_checksum_claim_invalid"
    assert not [u for u in session.updates if "status = 'ready'" in u[0]]


def test_a_ticket_with_no_bound_claim_is_refused_at_completion_and_given_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(_pending(None))
    answer = _client(session, _Store(size=12), monkeypatch).post(
        f"/api/v1/files/{FILE_A}/complete", json={"checksum_sha256": DIGEST}
    )
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] == "upload_checksum_claim_invalid"
    assert not [u for u in session.updates if "status = 'ready'" in u[0]], "no claim was invented"


def test_completion_with_no_body_digest_still_uses_the_bound_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(_pending(DIGEST))
    answer = _client(session, _Store(size=12), monkeypatch).post(
        f"/api/v1/files/{FILE_A}/complete", json={}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["checksum_sha256"] == DIGEST


@pytest.mark.parametrize(
    "claim",
    [None, "", "not-a-digest", "AB" * 32, "ab" * 31, "ab" * 33, "zz" * 32, " " + "ab" * 32],
)
def test_a_ticket_without_a_valid_checksum_is_refused_and_no_row_or_url_is_made(
    monkeypatch: pytest.MonkeyPatch, claim: object
) -> None:
    session, store = _Session(), _Store()
    body: dict[str, object] = {"name": "a.pdf", "size_bytes": 12, "category": "documents"}
    if claim is not None:
        body["checksum_sha256"] = claim
    answer = _client(session, store, monkeypatch).post("/api/v1/files/uploads", json=body)
    assert answer.status_code == 422, answer.text
    assert "checksum_sha256" in answer.text, "the error names the field"
    assert session.inserted == [] and store.presigned == []


def test_a_null_checksum_is_refused_not_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store = _Session(), _Store()
    answer = _client(session, store, monkeypatch).post(
        "/api/v1/files/uploads",
        json={"name": "a.pdf", "size_bytes": 12, "checksum_sha256": None},
    )
    assert answer.status_code == 422, answer.text
    assert session.inserted == [] and store.presigned == []


def test_the_ticket_binds_the_claim_signs_the_guards_and_names_its_own_upload_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_storage import upload_guard_headers

    session, store = _Session(), _Store()
    answer = _client(session, store, monkeypatch).post(
        "/api/v1/files/uploads",
        json={"name": "a.pdf", "size_bytes": 12, "checksum_sha256": DIGEST},
    )
    assert answer.status_code == 201, answer.text
    (row,) = session.inserted
    assert row["checksum"] == DIGEST, "the claim is bound to the row at issuance"
    assert store.claims == [DIGEST]
    (signed,) = store.presigned
    (upload_id,) = store.provenance
    assert upload_id is not None, "a secure ticket is always guarded"
    assert upload_id == signed.split("/")[5], "the provenance is the ticket's own upload id"
    headers = answer.json()["headers"]
    assert headers["x-amz-checksum-sha256"] == base64.b64encode(bytes.fromhex(DIGEST)).decode()
    for name, value in upload_guard_headers(upload_id).items():
        assert headers[name] == value, f"{name} must be sent exactly as signed"
    # A copy attempt must fail whatever it names: both preconditions are false for every source.
    assert headers["x-amz-copy-source-if-unmodified-since"].endswith("1970 00:00:00 GMT")
    assert headers["x-amz-metadata-directive"] == "COPY"


# --- nothing reads an incoming key -----------------------------------------------------------


def test_a_download_of_an_incoming_key_is_refused_before_anything_is_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _pending(DIGEST)
    ready.status = "ready"
    store = _Store()
    answer = _client(_Session(ready), store, monkeypatch).get(f"/api/v1/files/{FILE_A}/download")
    assert answer.status_code == 403, answer.text
    assert answer.json()["detail"]["code"] == "file_quarantined"
    assert store.downloads == []


def test_a_download_of_a_finalized_key_is_not_refused_for_being_finalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = final_key_for(incoming_key(TENANT_A, "documents", FILE_A, UPLOAD, "a.pdf"), GENERATION)
    ready = _pending(DIGEST, key=final)
    ready.status = "ready"
    store = _Store()
    answer = _client(_Session(ready), store, monkeypatch).get(f"/api/v1/files/{FILE_A}/download")
    assert answer.status_code == 200, answer.text
    assert store.downloads == [final]


# --- structure ---------------------------------------------------------------------------------


def _calls(tree: ast.AST, attribute: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == attribute
    ]


def test_the_only_upload_signature_is_over_a_key_made_by_incoming_key() -> None:
    api = REPO / "services/api/koras_api"
    signing: list[str] = []
    for path in api.rglob("*.py"):
        if _calls(ast.parse(path.read_text(encoding="utf-8")), "presign_upload"):
            signing.append(path.relative_to(api).as_posix())
    assert signing == ["routers/files.py"], signing

    tree = ast.parse((api / "routers/files.py").read_text(encoding="utf-8"))
    (call,) = _calls(tree, "presign_upload")
    first = call.args[0]
    assert isinstance(first, ast.Name) and first.id == "key"
    assigned = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "key" for t in n.targets)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
    ]
    assert [n.value.func.id for n in assigned] == ["incoming_key"]  # type: ignore[union-attr]
    # And the ticket is always guarded: the upload id is passed explicitly, never defaulted.
    keywords = {kw.arg for kw in call.keywords}
    assert "provenance" in keywords


def test_nothing_in_the_api_can_name_a_final_key() -> None:
    """The API holds no function that builds one: only the worker's finalizer does."""
    holders = []
    for root in ("services/api", "services/worker"):
        for path in (REPO / root).rglob("*.py"):
            if "final_key_for" in path.read_text(encoding="utf-8"):
                holders.append(path.relative_to(REPO).as_posix())
    # `upload_window.py` defines the shape (the worker image carries it); the API never calls it.
    assert sorted(holders) == [
        "services/api/koras_api/core/upload_window.py",
        "services/worker/koras_worker/uploads/finalize.py",
    ]


def test_the_api_never_imports_the_object_key_builder_for_uploads() -> None:
    source = (REPO / "services/api/koras_api/routers/files.py").read_text(encoding="utf-8")
    assert "object_key" not in source


def test_finalization_waits_longer_than_a_ticket_lives_and_longer_than_a_request_can_run() -> None:
    from koras_api.core.upload_window import (
        FINALIZE_DELAY_SECONDS,
        IN_FLIGHT_BOUND_SECONDS,
        SCAN_READ_DELAY_SECONDS,
        UPLOAD_URL_SECONDS,
    )

    assert IN_FLIGHT_BOUND_SECONDS >= 150, "the longest request the provider was measured to allow"
    assert FINALIZE_DELAY_SECONDS >= UPLOAD_URL_SECONDS + IN_FLIGHT_BOUND_SECONDS
    assert FINALIZE_DELAY_SECONDS > SCAN_READ_DELAY_SECONDS
    assert uuid.UUID(GENERATION)  # keep the import honest


def test_the_window_has_no_setting() -> None:
    """ADR 0013 section 6: nothing at deploy time may shorten the window."""
    from koras_api.core.settings import settings

    for name in vars(type(settings)).get("model_fields", {}):
        assert "upload_url" not in name and "finalize_delay" not in name, name
    assert timedelta(seconds=FINALIZE_DELAY_SECONDS) >= timedelta(minutes=19)
