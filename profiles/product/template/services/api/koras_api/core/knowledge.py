"""The knowledge index behind retrieval: pgvector, on the tenant session.

`koras_ai.knowledge` holds the contracts -- a document, its chunks, an index
that stores vectors and answers a query with citations. This is the store:
one table, `ai_knowledge_chunks`, under the same row-level security as
everything else the tenant owns, queried by cosine distance.

Ingestion is here too. A file that finished uploading and is text-like and
small enough is read back from the bucket, split with the runtime's chunker,
embedded through the gateway under the embedding alias, and written as
chunks. Anything else -- a PDF, an image, a spreadsheet, a file past the
size ceiling -- is skipped with a log line and no chunks, and the assistant
answers about it from its name alone. Extracting those is a follow-up with
a dependency of its own.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from koras_ai import Chunk, Citation, Document, RetrievalScope, SimpleChunker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: What is read as text. A content type not here is not indexed.
INDEXABLE_TYPES: frozenset[str] = frozenset(
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

#: Past this, a file is skipped rather than embedded in hundreds of calls.
MAX_INDEX_BYTES = 1_000_000

#: Chunks per query. Enough to answer from, few enough to fit a prompt.
DEFAULT_LIMIT = 5

Embed = Callable[[Sequence[str]], Awaitable[list[tuple[float, ...]]]]


def extract_text(raw: bytes, *, content_type: str) -> str | None:
    """The file as text, or None when it is not the kind of file that is text."""
    base = content_type.split(";", 1)[0].strip().lower()
    if base not in INDEXABLE_TYPES:
        return None
    if len(raw) > MAX_INDEX_BYTES:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if base == "text/html":
        decoded = _strip_tags(decoded)
    stripped = decoded.strip()
    return stripped or None


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
    " and (:resource_type is null or resource_type = :resource_type) "
    " and (:resource_id is null or resource_id = :resource_id) "
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
