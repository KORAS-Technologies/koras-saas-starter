"""The file tools: a rename renames, a delete deletes, both scoped to the tenant."""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_ai import ToolContext  # noqa: E402
from koras_api.ai.tools import (  # noqa: E402
    DeleteFileInput,
    RenameFileInput,
    delete_file,
    rename_file,
)
from test_ai_api import OWNER, context  # noqa: E402

FILE_ID = "31055174-7afb-4a70-8e3b-1bb0b5dd250b"


class _Row:
    id = FILE_ID
    name = "Invoice-0008.pdf"
    storage_key = "tenants/t/31055174/Invoice-0008.pdf"


class _Session:
    def __init__(self, row: object | None) -> None:
        self._row = row
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = 0

    async def execute(
        self, statement: object, parameters: dict[str, Any] | None = None
    ) -> _Session:
        self.calls.append((str(statement).split("\n")[0][:70], parameters))
        return self

    def first(self) -> object | None:
        return self._row

    async def commit(self) -> None:
        self.committed += 1


class _Store:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def _ctx(session: _Session, store: _Store | None = None) -> ToolContext:
    async def store_for() -> _Store:
        return store or _Store()

    return ToolContext(
        context=context("owner", OWNER, frozenset({"organization_owner"})),
        session=session,
        services={"storage": store_for},
    )


async def test_a_rename_changes_the_name_and_the_index_title_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_api.ai import tools as tools_module

    async def rebind(bound: object, tenant_id: str) -> None:
        session.calls.append(("rebind", None))

    monkeypatch.setattr(tools_module, "rebind_tenant", rebind)
    session = _Session(_Row())
    answer = await rename_file(
        _ctx(session), RenameFileInput(file_id=FILE_ID, new_name="Invoice vercel/sept.pdf")
    )
    assert answer == {"renamed": "Invoice-0008.pdf", "to": "sept.pdf"}
    statements = [c[0] for c in session.calls]
    assert any(s.startswith("update public.files set name") for s in statements)
    assert any(s.startswith("update public.ai_knowledge_chunks set title") for s in statements)
    assert not any("delete" in s for s in statements)
    assert session.committed == 1
    # Every statement names the tenant; the tenant is bound again after the commit.
    tenant = context("owner", OWNER, frozenset({"organization_owner"})).tenant_id
    assert all(c[1] is None or c[1].get("tenant_id") == tenant for c in session.calls[:-1])
    assert statements[-1] == "rebind"


async def test_a_delete_removes_the_object_the_chunks_and_the_row_in_that_order() -> None:
    session = _Session(_Row())
    store = _Store()
    answer = await delete_file(_ctx(session, store), DeleteFileInput(file_id=FILE_ID))
    assert answer == {"deleted": "Invoice-0008.pdf"}
    assert store.deleted == [_Row.storage_key]
    statements = [c[0] for c in session.calls]
    chunks = next(i for i, s in enumerate(statements) if "ai_knowledge_chunks" in s)
    row = next(i for i, s in enumerate(statements) if s.startswith("delete from public.files"))
    assert chunks < row
    assert session.committed == 1


async def test_a_file_that_is_not_the_tenants_is_not_found() -> None:
    session = _Session(None)
    assert (await rename_file(_ctx(session), RenameFileInput(file_id=FILE_ID, new_name="x")))[
        "renamed"
    ] is None
    assert (await delete_file(_ctx(session), DeleteFileInput(file_id=FILE_ID)))["deleted"] is None
    assert session.committed == 0
