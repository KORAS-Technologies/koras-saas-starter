"""Upload completion hands the assistant nothing; the list offers it a clean file (`secure_files`).

Over a scripted session and a recording store, as `test_files_release_api.py`. What is
asserted is the boundary the router owns: that completing an upload signs no URL and
calls no hook whatever is registered, that the list offers a hook only a `clean` file
it still has work for -- never `pending`, `skipped`, `infected`, NULL or unknown, never
another tenant's, never more than the cap -- and that the caller's token reaches the
hook in memory and nowhere else. The same rules against a real PostgreSQL are
`tests/integration/test_file_derived_content_real.py`.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.file_hooks import FileHook, hooks  # noqa: E402
from koras_api.routers import files as files_router  # noqa: E402
from release_support import (  # noqa: E402
    FILE_ID,
    OTHER_TENANT,
    TENANT,
    Session,
    Store,
    clear_overrides,
    client,
    file_row,
)

_Session, _Store, _client, _file = Session, Store, client, file_row

REPO = Path(__file__).resolve().parents[2]
TOKEN = "SECRET-CALLER-TOKEN-0123456789"  # noqa: S105 - a marker, not a credential
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _SpySession(_Session):
    """Also keeps every parameter any statement was sent with."""

    def __init__(self, files: list[SimpleNamespace]) -> None:
        super().__init__(files)
        self.sent: list[Any] = []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        self.sent.append(parameters)
        return await super().execute(statement, parameters)


class _Calls:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def after_clean(self, **arguments: Any) -> int:  # noqa: ANN401
        self.calls.append(arguments)
        return 1


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    clear_overrides()


@pytest.fixture
def recorder() -> Iterator[_Calls]:
    hooks.clear()
    calls = _Calls()
    hooks.add(
        FileHook(
            name="knowledge",
            interested=lambda content_type: content_type == "application/pdf",
            due=lambda indexed_at, note: indexed_at is None and note is None,
            after_clean=calls.after_clean,
        )
    )
    yield calls
    hooks.clear()


def _row(scan_status: Any, index: int | None = None, **overrides: Any) -> SimpleNamespace:  # noqa: ANN401
    row = _file(scan_status, **{k: v for k, v in overrides.items() if k in {"status", "tenant"}})
    if index is not None:
        row.id = f"11111111-1111-1111-1111-1111111111{index:02d}"
    for key in ("indexed_at", "index_note", "content_type"):
        if key in overrides:
            setattr(row, key, overrides[key])
    return row


# -- upload completion ----------------------------------------------------------


def test_completing_an_upload_signs_no_url_calls_no_hook_and_says_unavailable(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with a hook interested in this very type, and a bearer token on the request."""
    from test_upload_finalization import DIGEST, FILE_A
    from test_upload_finalization import _client as completion_client
    from test_upload_finalization import _pending as pending_row
    from test_upload_finalization import _Session as CompletionSession
    from test_upload_finalization import _Store as CompletionStore

    session, store = CompletionSession(pending_row(DIGEST)), CompletionStore(size=12)
    answer = completion_client(session, store, monkeypatch).post(
        f"/api/v1/files/{FILE_A}/complete", json={}, headers=AUTH
    )
    assert answer.status_code == 200, answer.text
    assert store.downloads == [], "a signed GET before the verdict is a read capability"
    assert recorder.calls == []
    assert TOKEN not in answer.text
    assert answer.json()["scan_status"] == "pending"
    assert answer.json()["content_available"] is False
    clear_overrides()


# -- the list's offer -----------------------------------------------------------


def test_a_clean_file_with_work_to_do_is_offered_once_with_no_url_and_no_key(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, store = _SpySession([_row("clean")]), _Store()
    answer = _client(session, store, monkeypatch).get("/api/v1/files", headers=AUTH)
    assert answer.status_code == 200, answer.text
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["file_id"] == FILE_ID
    assert call["tenant_id"] == TENANT
    assert call["token"] == TOKEN
    assert call["store"] is store
    assert set(call) == {
        "tenant_id",
        "organization_id",
        "token",
        "file_id",
        "user_id",
        "store",
    }, "no url, no storage key, no name: the hook reads through the release gate"
    assert store.signed == []


# NULL and a non-string cannot reach the list: the column is NOT NULL with a CHECK, and the
# response model would refuse them. `releasable()` withholds both
# (`test_file_release.py`), and the real-database suite crosses every stored state.
@pytest.mark.parametrize("scan_status", ["pending", "skipped", "infected", "", "CLEAN", "weird"])
def test_a_file_that_is_not_clean_is_never_offered(
    scan_status: Any,  # noqa: ANN401
    recorder: _Calls,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, store = _SpySession([_row(scan_status)]), _Store()
    answer = _client(session, store, monkeypatch).get("/api/v1/files", headers=AUTH)
    assert answer.status_code == 200, answer.text
    assert recorder.calls == []
    assert store.signed == []


def test_a_clean_file_that_is_not_ready_is_never_offered(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The list selects only ready rows; a quarantined clean one is not in it at all."""
    session = _SpySession([_row("clean", status="quarantined")])
    _client(session, _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert recorder.calls == []


def test_another_tenants_clean_file_is_never_offered(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _SpySession([_row("clean", tenant=OTHER_TENANT)])
    answer = _client(session, _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert answer.json()["files"] == []
    assert recorder.calls == []


def test_a_file_already_indexed_or_already_tried_is_not_offered_again(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _row("clean", 1, indexed_at=datetime(2026, 10, 5, tzinfo=UTC)),
        _row("clean", 2, index_note="no text to index"),
    ]
    _client(_SpySession(rows), _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert recorder.calls == []


def test_a_type_no_hook_wants_is_not_offered(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [_row("clean", 1, content_type="application/zip")]
    _client(_SpySession(rows), _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert recorder.calls == []


def test_one_listing_offers_at_most_the_cap(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [_row("clean", index) for index in range(8)]
    answer = _client(_SpySession(rows), _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert len(answer.json()["files"]) == 8
    assert len(recorder.calls) == files_router.LAZY_HOOKS_PER_LIST == 3


def test_without_a_bearer_token_nothing_is_offered(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offer runs on the caller's own authority; with none in hand there is no offer."""
    answer = _client(_SpySession([_row("clean")]), _Store(), monkeypatch).get("/api/v1/files")
    assert answer.status_code == 200
    assert recorder.calls == []


def test_the_token_reaches_the_hook_in_memory_and_is_written_nowhere(
    recorder: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _SpySession([_row("clean")])
    answer = _client(session, _Store(), monkeypatch).get("/api/v1/files", headers=AUTH)
    assert recorder.calls[0]["token"] == TOKEN
    assert TOKEN not in str(session.sent), "no statement was sent the token"
    assert TOKEN not in str(session.audit)
    assert TOKEN not in answer.text
    assert TOKEN not in str(answer.headers)


# -- static: the token is not queued, stored or logged -------------------------


def _function(path: Path, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def test_the_bearer_credentials_are_used_in_one_function_of_the_files_router() -> None:
    """`credentials` is the caller's token. Only the list may read it, to hand it to a hook."""
    path = REPO / "services/api/koras_api/routers/files.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    users = set()
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
        names = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
        names |= {a.arg for a in function.args.args}
        if "credentials" in names:
            users.add(function.name)
    assert users == {"list_files"}, users


def test_nothing_that_indexes_touches_a_queue_a_cache_or_a_log_of_the_token() -> None:
    """The caller's token lives in the call: no enqueue, no Redis, no job, no log line."""
    for name in ("core/file_indexing.py", "core/knowledge.py", "core/file_release_gate.py"):
        path = REPO / "services/api/koras_api" / name
        if not path.exists():
            continue  # a product without the assistant has no indexer to guard
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert not used & {"enqueue", "enqueue_job", "redis", "jobs", "JobsDep", "token"}, name
    ai_path = REPO / "services/api/koras_api/core/ai.py"
    if not ai_path.exists():
        return
    ai = ast.parse(ai_path.read_text(encoding="utf-8"))
    indexer = {
        n.name: n for n in ast.walk(ai) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    for name in ("index_clean_file", "_index_clean_file", "_record_index"):
        for call in (n for n in ast.walk(indexer[name]) if isinstance(n, ast.Call)):
            target = ast.unparse(call.func)
            if target.startswith(("_log.", "logging.", "logger.")):
                assert "token" not in ast.unparse(call), (name, ast.unparse(call))
            assert "enqueue" not in target, (name, target)


def test_the_upload_route_no_longer_imports_the_hook_runner_or_signs_for_a_hook() -> None:
    complete = _function(REPO / "services/api/koras_api/routers/files.py", "complete_upload")
    names = {n.id for n in ast.walk(complete) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(complete) if isinstance(n, ast.Attribute)
    }
    assert not names & {"presign_download", "hooks", "run_after_clean", "credentials"}
