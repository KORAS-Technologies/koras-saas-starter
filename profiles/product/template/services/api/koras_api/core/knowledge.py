"""The knowledge index behind retrieval: pgvector, on the tenant session.

`koras_ai.knowledge` holds the contracts -- a document, its chunks, an index
that stores vectors and answers a query with citations. This is the store:
one table, `ai_knowledge_chunks`, under the same row-level security as
everything else the tenant owns, queried by cosine distance.

Ingestion is here too. A file that finished uploading and has text in it --
plain text, Markdown, CSV, HTML, JSON, a PDF, a spreadsheet -- is read back
from the bucket, its text extracted, split with the runtime's chunker,
embedded through the gateway under the embedding alias, and written as
chunks. Anything else -- an image, an archive, a scanned PDF with no text
layer, a file past the size ceiling -- is skipped with a log line and no
chunks, and the assistant answers about it from its name alone.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from koras_ai import Chunk, Citation, Document, RetrievalScope, SimpleChunker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Content types read as text as they are.
TEXT_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "application/json",
        "application/x-yaml",
        "text/yaml",
    }
)

PDF_TYPE = "application/pdf"
SPREADSHEET_TYPES: frozenset[str] = frozenset(
    {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
)

IMAGE_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp"})

#: Every content type that can be indexed. A type not here is not.
INDEXABLE_TYPES: frozenset[str] = TEXT_TYPES | {PDF_TYPE} | SPREADSHEET_TYPES | IMAGE_TYPES
#: Types whose text may have to be seen rather than read: an image, or a
#: PDF whose pages are pictures of a page.
OCR_TYPES: frozenset[str] = IMAGE_TYPES | {PDF_TYPE}

#: Past this, a file is skipped rather than embedded in hundreds of calls.
#: A PDF or a workbook is mostly not text, so its ceiling is higher; what
#: bounds the embedding calls for those is MAX_TEXT_CHARS below.
MAX_INDEX_BYTES = 1_000_000
MAX_DOCUMENT_BYTES = 25_000_000
#: The most text one file contributes, whatever it holds. Roughly a hundred
#: thousand tokens, or eighty pages of dense prose; the rest is not indexed.
MAX_TEXT_CHARS = 400_000

#: Pages a scanned document is read for. Each is one vision call, so this
#: bounds what one upload can cost; the rest of a longer scan is not indexed.
MAX_OCR_PAGES = 20
#: Render scale for a PDF page: 1.0 is 72 dpi, 1.5 is enough for body text
#: and keeps a page under the size vision models accept.
OCR_RENDER_SCALE = 1.5
MAX_IMAGE_BYTES = 10_000_000

#: Chunks per query. Enough to answer from, few enough to fit a prompt.
DEFAULT_LIMIT = 5

Embed = Callable[[Sequence[str]], Awaitable[list[tuple[float, ...]]]]
#: One page as an encoded image and its content type.
Page = tuple[bytes, str]
#: Reads pages back as text, one string per page, through a vision model.
ReadPages = Callable[[Sequence[Page]], Awaitable[list[str]]]


@dataclass(frozen=True)
class Extracted:
    """What a file gave for indexing and how: its text layer, or its pages read."""

    text: str | None
    #: "text" from a text layer or cells, "ocr" from its pages, "none" for nothing.
    method: str
    pages: int = 0


def content_kind(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def is_indexable(content_type: str) -> bool:
    """Whether a file of this type is worth reading back for its text."""
    return content_kind(content_type) in INDEXABLE_TYPES


def extract_text(raw: bytes, *, content_type: str) -> str | None:
    """The file as text, or None when it has none to give.

    None for a type that is not indexed, a file past its size ceiling, a
    text file that is not UTF-8, a PDF with no text layer, a workbook with
    no cells. The text is bounded by MAX_TEXT_CHARS whatever the source.
    """
    kind = content_kind(content_type)
    if kind in TEXT_TYPES:
        if len(raw) > MAX_INDEX_BYTES:
            return None
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        text_content: str | None = _strip_tags(decoded) if kind == "text/html" else decoded
    elif kind == PDF_TYPE:
        text_content = _pdf_text(raw) if len(raw) <= MAX_DOCUMENT_BYTES else None
    elif kind in SPREADSHEET_TYPES:
        text_content = _workbook_text(raw) if len(raw) <= MAX_DOCUMENT_BYTES else None
    else:
        return None
    if text_content is None:
        return None
    stripped = text_content.strip()[:MAX_TEXT_CHARS]
    return stripped or None


def page_images(raw: bytes, *, content_type: str) -> list[Page]:
    """The file as images, one per page, for a model that reads pictures.

    An image is its own single page. A PDF is rendered page by page, up to
    MAX_OCR_PAGES. Anything else, or anything past its size ceiling, is no
    pages. CPU-bound for a PDF; call it off the event loop.
    """
    kind = content_kind(content_type)
    if kind in IMAGE_TYPES:
        return [(raw, kind)] if len(raw) <= MAX_IMAGE_BYTES else []
    if kind == PDF_TYPE:
        return _pdf_pages(raw) if len(raw) <= MAX_DOCUMENT_BYTES else []
    return []


def _pdf_pages(raw: bytes) -> list[Page]:
    """Each page rendered to a PNG, in order, up to the page ceiling."""
    from io import BytesIO

    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    try:
        document = pdfium.PdfDocument(raw)
    except Exception:
        logger.info("a PDF could not be opened for rendering")
        return []
    pages: list[Page] = []
    try:
        for index in range(min(len(document), MAX_OCR_PAGES)):
            page = document[index]
            try:
                bitmap = page.render(scale=OCR_RENDER_SCALE)
                buffer = BytesIO()
                bitmap.to_pil().save(buffer, format="PNG")
                pages.append((buffer.getvalue(), "image/png"))
            finally:
                page.close()
    except Exception:
        logger.info("a PDF page could not be rendered; the pages before it are read")
    finally:
        document.close()
    return pages


async def text_for_index(raw: bytes, *, content_type: str, read: ReadPages | None) -> Extracted:
    """The file's text, read from its text layer first and its pages second.

    The text layer costs nothing and is exact, so it always wins. Pages are
    read only when there is no text layer to read, only for the types that
    have pages, and only when a reader was given -- an indexer with no
    vision route reads nothing rather than failing the upload.
    """
    text_content = extract_text(raw, content_type=content_type)
    if text_content is not None:
        return Extracted(text_content, "text")
    if read is None or content_kind(content_type) not in OCR_TYPES:
        return Extracted(None, "none")
    pages = await asyncio.to_thread(page_images, raw, content_type=content_type)
    if not pages:
        return Extracted(None, "none")
    transcribed = await read(pages)
    joined = "\n\n".join(page.strip() for page in transcribed if page and page.strip())
    stripped = joined[:MAX_TEXT_CHARS].strip()
    return Extracted(stripped or None, "ocr", len(pages))


def _pdf_text(raw: bytes) -> str | None:
    """Every page's text layer, pages separated by a blank line.

    A scanned PDF has no text layer and answers empty, which is None here:
    reading it needs OCR, which is a dependency and a cost of its own and
    not something to do to every upload unasked.
    """
    from io import BytesIO

    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        logger.info("a PDF could not be read for indexing")
        return None
    joined = "\n\n".join(page.strip() for page in pages if page.strip())
    return joined or None


def _workbook_text(raw: bytes) -> str | None:
    """Every sheet as lines of tab-separated cell values, headed by its name.

    Values, not formulas: what a person sees in the cell is what a question
    is about. Empty rows and empty sheets are left out.
    """
    from io import BytesIO

    from openpyxl import load_workbook

    try:
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        logger.info("a workbook could not be read for indexing")
        return None
    sections: list[str] = []
    try:
        for sheet in workbook.worksheets:
            lines: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value).strip() for value in row]
                if any(cells):
                    lines.append("\t".join(cells).rstrip())
            if lines:
                sections.append(f"Sheet: {sheet.title}\n" + "\n".join(lines))
    finally:
        workbook.close()
    return "\n\n".join(sections) or None


def _strip_tags(html: str) -> str:
    out: list[str] = []
    inside = False
    for char in html:
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
            out.append(" ")
        elif not inside:
            out.append(char)
    return "".join(out)


def _literal(vector: Sequence[float]) -> str:
    """A pgvector literal: `[0.1,0.2,...]`, six decimals, no spaces."""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


_UPSERT = text(
    "insert into public.ai_knowledge_chunks "
    "(tenant_id, document_id, resource_type, resource_id, title, chunk_index, content, "
    " embedding, metadata) "
    "values (:tenant_id, :document_id, :resource_type, :resource_id, :title, :chunk_index, "
    " :content, cast(:embedding as vector), cast(:metadata as jsonb)) "
    "on conflict (tenant_id, document_id, chunk_index) do update set "
    " content = excluded.content, embedding = excluded.embedding, "
    " metadata = excluded.metadata, title = excluded.title"
)

_DELETE = text(
    "delete from public.ai_knowledge_chunks "
    "where tenant_id = :tenant_id and document_id = :document_id"
)

_DELETE_RESOURCE = text(
    "delete from public.ai_knowledge_chunks "
    "where tenant_id = :tenant_id and resource_type = :resource_type "
    " and resource_id = :resource_id"
)

_TRIM = text(
    "delete from public.ai_knowledge_chunks "
    "where tenant_id = :tenant_id and document_id = :document_id "
    " and chunk_index >= :count"
)

_QUERY = text(
    "select id::text as chunk_id, document_id, title, content, resource_type, resource_id, "
    " 1 - (embedding <=> cast(:embedding as vector)) as score "
    "from public.ai_knowledge_chunks "
    "where tenant_id = :tenant_id "
    # Cast, because asyncpg cannot type a parameter that is only ever compared
    # with `is null`: the first real search on dev died on exactly that, with
    # "could not determine data type of parameter", and the session it left
    # behind was in an aborted transaction.
    " and (cast(:resource_type as text) is null or resource_type = cast(:resource_type as text)) "
    " and (cast(:resource_id as text) is null or resource_id = cast(:resource_id as text)) "
    "order by embedding <=> cast(:embedding as vector) "
    "limit :limit"
)


class SqlKnowledgeIndex:
    """`KnowledgeIndex` on the tenant session. Every statement names the tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, scope: RetrievalScope, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk")
        document_id = chunks[0].document_id if chunks else None
        for chunk, vector in zip(chunks, vectors, strict=True):
            if chunk.tenant_id != scope.tenant_id:
                raise ValueError("a chunk from another tenant cannot be indexed here")
            await self._session.execute(
                _UPSERT,
                {
                    "tenant_id": scope.tenant_id,
                    "document_id": chunk.document_id,
                    "resource_type": chunk.metadata.get("resource_type", scope.resource_type or ""),
                    "resource_id": chunk.metadata.get("resource_id", scope.resource_id or ""),
                    "title": chunk.metadata.get("title", ""),
                    "chunk_index": chunk.index,
                    "content": chunk.text,
                    "embedding": _literal(vector),
                    "metadata": json.dumps(dict(chunk.metadata)),
                },
            )
        if document_id is not None:
            # A re-indexed document that got shorter leaves no stale tail.
            await self._session.execute(
                _TRIM,
                {"tenant_id": scope.tenant_id, "document_id": document_id, "count": len(chunks)},
            )
        await self._session.commit()

    async def delete(self, scope: RetrievalScope, document_id: str) -> None:
        await self._session.execute(
            _DELETE, {"tenant_id": scope.tenant_id, "document_id": document_id}
        )
        await self._session.commit()

    async def query(
        self, scope: RetrievalScope, vector: Sequence[float], *, limit: int
    ) -> list[Citation]:
        rows = await self._session.execute(
            _QUERY,
            {
                "tenant_id": scope.tenant_id,
                "resource_type": scope.resource_type,
                "resource_id": scope.resource_id,
                "embedding": _literal(vector),
                "limit": max(1, min(limit, 20)),
            },
        )
        return [
            Citation(
                document_id=str(row.document_id),
                chunk_id=str(row.chunk_id),
                title=str(row.title),
                snippet=str(row.content)[:400],
                score=float(row.score),
                resource_type=str(row.resource_type),
                resource_id=str(row.resource_id),
            )
            for row in rows.fetchall()
        ]


async def delete_resource(
    session: AsyncSession, *, tenant_id: str, resource_type: str, resource_id: str
) -> None:
    """Every chunk of one resource -- called when the file goes."""
    await session.execute(
        _DELETE_RESOURCE,
        {"tenant_id": tenant_id, "resource_type": resource_type, "resource_id": resource_id},
    )


async def index_document(
    session: AsyncSession, *, scope: RetrievalScope, document: Document, embed: Embed
) -> int:
    """Chunk, embed and store one document. Returns the chunk count."""
    chunks = SimpleChunker().chunk(document)
    if not chunks:
        await SqlKnowledgeIndex(session).delete(scope, document.id)
        return 0
    vectors = await embed([chunk.text for chunk in chunks])
    await SqlKnowledgeIndex(session).upsert(scope, chunks, vectors)
    return len(chunks)


def file_document(*, tenant_id: str, file_id: str, name: str, text_content: str) -> Document:
    return Document(
        id=f"file:{file_id}",
        source_id="files",
        tenant_id=tenant_id,
        resource_type="file",
        resource_id=file_id,
        title=name,
        text=text_content,
        metadata={"resource_type": "file", "resource_id": file_id, "title": name},
    )


async def search(
    session: AsyncSession, *, scope: RetrievalScope, query: str, embed: Embed, limit: int
) -> list[Citation]:
    vectors = await embed([query])
    if not vectors:
        return []
    return await SqlKnowledgeIndex(session).query(scope, vectors[0], limit=limit)


def citations_view(citations: Sequence[Citation]) -> list[dict[str, Any]]:
    """What a tool hands the model: the file, the snippet, the score. Data."""
    return [
        {
            "file_id": citation.resource_id,
            "file_name": citation.title,
            "snippet": citation.snippet,
            "score": round(citation.score, 3),
        }
        for citation in citations
    ]
