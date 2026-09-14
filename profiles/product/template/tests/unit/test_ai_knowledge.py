"""Retrieval: what is indexed, how it is stored, and what the tool hands the model."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_ai import RetrievalScope, ToolContext  # noqa: E402
from koras_api.ai.tools import SearchInput, search_knowledge  # noqa: E402
from koras_api.core import knowledge  # noqa: E402
from test_ai_api import OWNER, context  # noqa: E402


class _Session:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._rows = rows or []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.calls.append((str(statement).split("\n")[0][:60], parameters))
        return _Rows(self._rows)

    async def commit(self) -> None:
        self.calls.append(("commit", None))


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class _Row:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


async def _embed(texts: Sequence[str]) -> list[tuple[float, ...]]:
    return [(float(len(text)), 0.5) for text in texts]


def _pdf_with(text_line: str) -> bytes:
    """The smallest PDF with a text layer: one page, one line, Helvetica."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text_line}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _workbook_with(rows: list[list[object]]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Invoices"
    for row in rows:
        sheet.append(row)
    book.create_sheet("Empty")
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_a_pdf_gives_its_text_layer_and_a_scan_gives_nothing() -> None:
    text = knowledge.extract_text(
        _pdf_with("Invoice 42 is due Friday"), content_type="application/pdf"
    )
    assert text is not None and "Invoice 42 is due Friday" in text
    assert knowledge.extract_text(_pdf_with(""), content_type="application/pdf") is None
    assert knowledge.extract_text(b"not a pdf at all", content_type="application/pdf") is None


def test_a_workbook_gives_its_cells_as_lines_per_sheet() -> None:
    text = knowledge.extract_text(
        _workbook_with([["Customer", "Amount"], ["Acme", 1200], [None, None], ["Globex", 80.5]]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert text is not None
    assert text.startswith("Sheet: Invoices")
    assert "Customer\tAmount" in text and "Acme\t1200" in text and "Globex\t80.5" in text
    # The empty sheet and the empty row add nothing.
    assert "Empty" not in text and "\n\n\n" not in text


def test_the_indexable_check_is_by_type_alone() -> None:
    assert knowledge.is_indexable("application/pdf")
    assert knowledge.is_indexable("text/markdown; charset=utf-8")
    assert not knowledge.is_indexable("image/png")
    assert not knowledge.is_indexable("application/vnd.ms-excel")


def test_only_small_text_like_files_are_read_as_text() -> None:
    assert knowledge.extract_text(b"hello  world", content_type="text/plain") == "hello  world"
    assert (
        knowledge.extract_text(b"<p>Hi <b>there</b></p>", content_type="text/html") == "Hi  there"
    )
    assert knowledge.extract_text(b'{"a": 1}', content_type="application/json; charset=utf-8")
    assert knowledge.extract_text(b"\x89PNG", content_type="image/png") is None
    assert knowledge.extract_text(b"\xff\xfe", content_type="text/plain") is None
    assert knowledge.extract_text(b"   ", content_type="text/plain") is None
    assert (
        knowledge.extract_text(b"x" * (knowledge.MAX_INDEX_BYTES + 1), content_type="text/plain")
        is None
    )


async def test_a_file_is_chunked_embedded_and_upserted_under_its_tenant() -> None:
    session = _Session()
    scope = RetrievalScope(tenant_id="tenant-1", product_code="sample")
    document = knowledge.file_document(
        tenant_id="tenant-1", file_id="f1", name="notes.md", text_content="alpha " * 400
    )

    count = await knowledge.index_document(
        session,  # type: ignore[arg-type]
        scope=scope,
        document=document,
        embed=_embed,
    )

    assert count >= 2
    inserts = [c for c in session.calls if c[0].startswith("insert into public.ai_knowledge")]
    assert len(inserts) == count
    first = inserts[0][1]
    assert first is not None
    assert first["tenant_id"] == "tenant-1"
    assert first["document_id"] == "file:f1"
    assert first["resource_type"] == "file" and first["resource_id"] == "f1"
    assert first["title"] == "notes.md"
    assert first["embedding"].startswith("[") and first["embedding"].endswith("]")
    # The stale tail of a re-indexed document is trimmed, then committed.
    assert any(c[0].startswith("delete from public.ai_knowledge") for c in session.calls)
    assert session.calls[-1][0] == "commit"


async def test_a_chunk_from_another_tenant_is_refused() -> None:
    session = _Session()
    scope = RetrievalScope(tenant_id="tenant-2", product_code="sample")
    document = knowledge.file_document(
        tenant_id="tenant-1", file_id="f1", name="notes.md", text_content="alpha"
    )
    try:
        await knowledge.index_document(
            session,  # type: ignore[arg-type]
            scope=scope,
            document=document,
            embed=_embed,
        )
    except ValueError as refused:
        assert "another tenant" in str(refused)
    else:
        raise AssertionError("a chunk was indexed under the wrong tenant")


async def test_the_search_tool_hands_the_model_snippets_and_file_names_only() -> None:
    rows = [
        _Row(
            chunk_id="c1",
            document_id="file:f1",
            title="notes.md",
            content="The invoice is due on the 14th.",
            resource_type="file",
            resource_id="f1",
            score=0.91,
        )
    ]
    session = _Session(rows)

    async def retrieve(query: str, limit: int) -> list[Any]:
        scope = RetrievalScope(tenant_id="tenant-1", product_code="sample")
        return await knowledge.search(
            session,  # type: ignore[arg-type]
            scope=scope,
            query=query,
            embed=_embed,
            limit=limit,
        )

    ctx = ToolContext(
        context=context("owner", OWNER, frozenset({"organization_owner"})),
        session=session,
        services={"retrieve": retrieve},
    )
    answer = await search_knowledge(ctx, SearchInput(query="when is the invoice due", limit=3))

    assert answer["results"] == [
        {
            "file_id": "f1",
            "file_name": "notes.md",
            "snippet": "The invoice is due on the 14th.",
            "score": 0.91,
        }
    ]
    query = next(c for c in session.calls if c[0].startswith("select id::text"))
    assert query[1] is not None and query[1]["tenant_id"] == "tenant-1" and query[1]["limit"] == 3


async def test_the_search_tool_says_so_when_retrieval_is_not_available() -> None:
    ctx = ToolContext(
        context=context("owner", OWNER, frozenset({"organization_owner"})),
        session=None,
        services={},
    )
    answer = await search_knowledge(ctx, SearchInput(query="anything"))
    assert answer["results"] == [] and "not available" in answer["note"]
