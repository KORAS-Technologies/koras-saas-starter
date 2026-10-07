"""Static guards for the derived-content withdrawal (`secure_files`, migration 00042).

Defence in depth beside `test_file_derived_content_real.py`, which proves the behaviour
against a real PostgreSQL. These keep the shape: the trigger reacts to a verdict and
writes none, the scanner is untouched, and the one writer of file chunks is the guarded one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API = REPO / "services/api/koras_api"
MIGRATION = REPO / "supabase/migrations/00042_file_derived_content_withdrawal.sql"


def _sql() -> str:
    """The migration without its comments."""
    return "\n".join(
        line
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not line.startswith("--")
    )


def test_the_trigger_is_a_before_update_row_trigger_that_fires_only_when_releasable_ends() -> None:
    sql = _sql()
    assert re.search(
        r"create trigger files_withdraw_derived_content\s+before update on public\.files\s+for each row",  # noqa: E501
        sql,
    )
    when = sql.split("when (")[1].split(")\n  execute")[0]
    assert "old.status = 'ready' and old.scan_status = 'clean'" in when
    assert "not (new.status = 'ready' and new.scan_status = 'clean')" in when


def test_the_function_is_definer_with_a_pinned_path_and_is_not_callable_by_anyone() -> None:
    sql = _sql()
    assert "security definer" in sql
    assert "set search_path = pg_catalog, public, pg_temp" in sql
    assert "revoke all on function public.withdraw_file_derived_content() from public" in sql
    assert "returns trigger" in sql


def test_the_function_deletes_only_this_rows_files_chunks_and_writes_no_verdict() -> None:
    body = _sql().split("as $$")[1].split("$$;")[0]
    deletes = re.findall(r"delete from ([\w.]+)", body)
    assert deletes == ["public.ai_knowledge_chunks"]
    # Skipped, not failed, where the product has no assistant and so no such table.
    assert "if to_regclass('public.ai_knowledge_chunks') is not null then" in body
    assert "tenant_id = old.tenant_id" in body
    assert "resource_type = 'file'" in body
    assert "resource_id = old.id::text" in body
    assert not re.search(r"\b(insert|update)\b", body.replace("new.indexed_at", ""))
    assert "scan_status" not in body and "status" not in body.replace("new.index", "")


def test_the_migration_adds_no_column_no_index_and_no_policy() -> None:
    sql = _sql().lower()
    for forbidden in ("alter table", "create index", "create policy", "drop policy", "add column"):
        assert forbidden not in sql, forbidden


def test_the_scanner_package_is_not_aware_of_derived_content() -> None:
    for path in (REPO / "services/worker/koras_worker/scanning").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for word in ("ai_knowledge_chunks", "indexed_at", "index_note", "withdraw"):
            assert word not in text, (path.name, word)


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }


def test_no_file_chunk_is_written_except_through_the_guarded_writer() -> None:
    """`index_document` is the unguarded one; only generic non-file sources could use it."""
    if not (API / "core/ai.py").exists():
        return  # no assistant, so no file chunk is written at all
    for path in API.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "knowledge.py":
            continue
        assert not any(call.endswith("index_document") for call in _calls(path)), path.name
    assert any(c.endswith("index_file_document") for c in _calls(API / "core/ai.py"))


def test_every_statement_that_reads_chunks_for_retrieval_carries_the_release_rule() -> None:
    if not (API / "core/knowledge.py").exists():
        return  # no assistant, so no chunk is retrieved
    source = (API / "core/knowledge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_QUERY" for t in node.targets)
        ):
            assert "RELEASABLE_SQL" in ast.unparse(node.value)
            return
    raise AssertionError("_QUERY not found")


def test_the_indexer_has_no_http_fetch_of_a_url() -> None:
    if not (API / "core/ai.py").exists():
        return
    text = (API / "core/ai.py").read_text(encoding="utf-8")
    assert "httpx" not in text
    assert "presign_download" not in text
