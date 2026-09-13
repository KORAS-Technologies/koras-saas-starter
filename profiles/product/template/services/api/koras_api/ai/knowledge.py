"""The knowledge sources this product exposes to retrieval.

None, by default, and that is the point: nothing is indexed and no table is
crawled until a product declares a source here and builds the pipeline that
fills an index. The contracts are in `koras_ai.knowledge`; the store behind
them is a product's decision, made in a design document of its own.

A declaration looks like this, for a product with a documents area:

    define_knowledge_source(
        id="documents",
        resource_type="document",
        description="The documents this organization has uploaded",
    )
"""

from __future__ import annotations

from koras_ai import KnowledgeSourceDefinition

SOURCES: tuple[KnowledgeSourceDefinition, ...] = ()
