"""Retrieval contracts: the interfaces a product implements when it needs RAG.

Nothing here reaches a database. This is the vocabulary -- documents, chunks,
citations, a scope -- and the seams -- extract, chunk, embed, index,
retrieve -- with one working default, a chunker, and one adapter, an embedder
over the provider boundary. A product that wants retrieval implements
`KnowledgeIndex` against whatever store its design chooses and registers the
sources it is willing to expose. Nothing is indexed by default and no table
is crawled: a knowledge source is a declaration, and only declared sources
retrieve.

Every retrieval carries a `RetrievalScope`, and a scope names a tenant. There
is no constructor for a scope without one, which is the tenant boundary
expressed as a type rather than as an instruction to the model.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import not_found
from .models import ModelAlias, ModelRoute
from .providers import AIProvider
from .types import EmbedRequest

_SOURCE_ID = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$")


@dataclass(frozen=True)
class RetrievalScope:
    """Whose knowledge a retrieval may see. The tenant is not optional."""

    tenant_id: str
    product_code: str
    resource_type: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.product_code.strip():
            raise ValueError("a retrieval scope needs a tenant and a product")


@dataclass(frozen=True)
class Document:
    id: str
    source_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    title: str
    text: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    tenant_id: str
    index: int
    text: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """What an answer points at: enough to show and to open, never the whole document."""

    document_id: str
    chunk_id: str
    title: str
    snippet: str
    score: float
    resource_type: str | None = None
    resource_id: str | None = None


class Extractor(Protocol):
    async def extract(self, raw: bytes, *, content_type: str) -> str: ...


class Chunker(Protocol):
    def chunk(self, document: Document) -> list[Chunk]: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class KnowledgeIndex(Protocol):
    async def upsert(
        self, scope: RetrievalScope, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None: ...

    async def delete(self, scope: RetrievalScope, document_id: str) -> None: ...

    async def query(
        self, scope: RetrievalScope, vector: Sequence[float], *, limit: int
    ) -> list[Citation]: ...


class Retriever(Protocol):
    async def retrieve(
        self, scope: RetrievalScope, query: str, *, limit: int
    ) -> list[Citation]: ...


class SimpleChunker:
    """Fixed-size character windows with overlap. Enough to start; not the last word."""

    def __init__(self, *, size: int = 1200, overlap: int = 150) -> None:
        if size < 1 or overlap < 0 or overlap >= size:
            raise ValueError("chunk size must be positive and overlap smaller than size")
        self._size = size
        self._overlap = overlap

    def chunk(self, document: Document) -> list[Chunk]:
        text = document.text
        chunks: list[Chunk] = []
        start = 0
        while start < len(text):
            piece = text[start : start + self._size]
            chunks.append(
                Chunk(
                    id=f"{document.id}:{len(chunks)}",
                    document_id=document.id,
                    tenant_id=document.tenant_id,
                    index=len(chunks),
                    text=piece,
                    metadata=dict(document.metadata),
                )
            )
            if start + self._size >= len(text):
                break
            start += self._size - self._overlap
        return chunks


class ProviderEmbedder:
    """Embeds through the provider boundary, under the embedding alias."""

    def __init__(self, provider: AIProvider, route: ModelRoute) -> None:
        self._provider = provider
        self._route = route
        self.alias = ModelAlias.EMBEDDING.value

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        result = await self._provider.embed(
            EmbedRequest(model=self.alias, inputs=tuple(texts)), route=self._route
        )
        return list(result.vectors)


class EmbeddingRetriever:
    """Embed the query, ask the index. The one retriever shape most products need."""

    def __init__(self, embedder: Embedder, index: KnowledgeIndex) -> None:
        self._embedder = embedder
        self._index = index

    async def retrieve(self, scope: RetrievalScope, query: str, *, limit: int) -> list[Citation]:
        vectors = await self._embedder.embed([query])
        if not vectors:
            return []
        return await self._index.query(scope, vectors[0], limit=limit)


DocumentLoader = Callable[[RetrievalScope, str], Awaitable[Document | None]]


@dataclass(frozen=True)
class KnowledgeSourceDefinition:
    """A kind of resource a product is willing to index and retrieve from."""

    id: str
    resource_type: str
    description: str = ""
    tenant_scoped: bool = True
    #: Loads one resource by id, under the scope. None for a source that is
    #: only ever indexed by a product's own pipeline.
    loader: DocumentLoader | None = None

    def __post_init__(self) -> None:
        if not _SOURCE_ID.match(self.id):
            raise ValueError(f"knowledge source id {self.id!r} must be lower-case")
        if not self.tenant_scoped:
            # Deliberately refused rather than allowed with a warning. A
            # source shared across tenants is a decision the platform would
            # have to make, and this repository has no such source.
            raise ValueError(f"knowledge source {self.id}: every source is tenant-scoped")


def define_knowledge_source(
    *,
    id: str,
    resource_type: str,
    description: str = "",
    tenant_scoped: bool = True,
    loader: DocumentLoader | None = None,
) -> KnowledgeSourceDefinition:
    return KnowledgeSourceDefinition(
        id=id,
        resource_type=resource_type,
        description=description,
        tenant_scoped=tenant_scoped,
        loader=loader,
    )


class KnowledgeRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, KnowledgeSourceDefinition] = {}

    def add(self, source: KnowledgeSourceDefinition) -> KnowledgeSourceDefinition:
        if source.id in self._sources:
            raise ValueError(f"knowledge source {source.id} is already registered")
        self._sources[source.id] = source
        return source

    def get(self, source_id: str) -> KnowledgeSourceDefinition:
        source = self._sources.get(source_id)
        if source is None:
            raise not_found("knowledge source")
        return source

    def for_resource(self, resource_type: str) -> tuple[KnowledgeSourceDefinition, ...]:
        return tuple(s for s in self._sources.values() if s.resource_type == resource_type)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    def all(self) -> Iterable[KnowledgeSourceDefinition]:
        return tuple(self._sources.values())


def citations_as_text(citations: Sequence[Citation]) -> str:
    """Citations rendered for a prompt: numbered, titled, quoted.

    Data, not instructions. The text a chunk holds is whatever a customer
    put there, and the prompt that carries it says so.
    """
    lines = [
        f"[{index + 1}] {citation.title}: {citation.snippet}"
        for index, citation in enumerate(citations)
    ]
    return "\n".join(lines)


def metadata_for(scope: RetrievalScope, extra: Mapping[str, Any] | None = None) -> dict[str, str]:
    """The metadata every chunk carries, so an index can be filtered by it."""
    out = {"tenant_id": scope.tenant_id, "product_code": scope.product_code}
    if scope.resource_type:
        out["resource_type"] = scope.resource_type
    if scope.resource_id:
        out["resource_id"] = scope.resource_id
    for key, value in (extra or {}).items():
        out[str(key)] = str(value)
    return out
