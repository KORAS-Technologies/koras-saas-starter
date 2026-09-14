"""The Koras AI foundation.

What a product imports to define its agents, tools, prompts and knowledge
sources, and what the API imports to run them. Provider calls go through the
AI gateway and nowhere else; product code names model aliases and never a
provider's model; every tool is registered, typed and permissioned; nothing
executes on a model's say-so.

See `docs/AI_ARCHITECTURE.md` in the starter for the shape, and
`docs/AI_DEVELOPER_GUIDE.md` for how a product uses it.
"""

from .actions import OPEN, ActionStatus, ProposedAction
from .agents import AgentDefinition, AgentRegistry, Capability, define_agent
from .config import AIConfiguration, AliasPolicy, Limits, RoutingSource, StaticRouting
from .context import AIContext, PageContext
from .errors import AIError, ErrorCode
from .knowledge import (
    Chunk,
    Chunker,
    Citation,
    Document,
    Embedder,
    EmbeddingRetriever,
    Extractor,
    KnowledgeIndex,
    KnowledgeRegistry,
    KnowledgeSourceDefinition,
    ProviderEmbedder,
    RetrievalScope,
    Retriever,
    SimpleChunker,
    citations_as_text,
    define_knowledge_source,
    metadata_for,
)
from .models import ModelAlias, ModelCatalogue, ModelRoute, is_alias
from .policy import APPROVE_PERMISSION, USE_PERMISSION, Decision, decide, may_decide, visible_tools
from .prompts import PromptDefinition, PromptRegistry, define_prompt
from .providers import (
    AIProvider,
    FailingProvider,
    FakeProvider,
    GatewayProvider,
    ProviderRegistry,
)
from .runtime import AIRuntime, RuntimeStatus, Turn
from .store import Conversation, ConversationStore, InMemoryStore, StoredMessage
from .tools import (
    NEEDS_APPROVAL,
    Operation,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    define_tool,
)
from .types import (
    EmbedRequest,
    EmbedResult,
    GenerateEvent,
    GenerateRequest,
    GenerateResult,
    Message,
    Price,
    ToolCall,
    ToolSpec,
    Usage,
    estimated_cost_micros,
)
from .usage import UsageEvent, UsageRecorder, month_start

__all__ = [
    "APPROVE_PERMISSION",
    "NEEDS_APPROVAL",
    "OPEN",
    "USE_PERMISSION",
    "AIConfiguration",
    "AIContext",
    "AIError",
    "AIProvider",
    "AIRuntime",
    "ActionStatus",
    "AgentDefinition",
    "AgentRegistry",
    "AliasPolicy",
    "Capability",
    "Chunk",
    "Chunker",
    "Citation",
    "Conversation",
    "ConversationStore",
    "Decision",
    "Document",
    "EmbedRequest",
    "EmbedResult",
    "Embedder",
    "EmbeddingRetriever",
    "ErrorCode",
    "Extractor",
    "FailingProvider",
    "FakeProvider",
    "GatewayProvider",
    "GenerateEvent",
    "GenerateRequest",
    "GenerateResult",
    "InMemoryStore",
    "KnowledgeIndex",
    "KnowledgeRegistry",
    "KnowledgeSourceDefinition",
    "Limits",
    "Message",
    "ModelAlias",
    "ModelCatalogue",
    "ModelRoute",
    "Operation",
    "PageContext",
    "PromptDefinition",
    "PromptRegistry",
    "ProposedAction",
    "ProviderEmbedder",
    "ProviderRegistry",
    "Retriever",
    "RetrievalScope",
    "RoutingSource",
    "RuntimeStatus",
    "SimpleChunker",
    "StaticRouting",
    "StoredMessage",
    "ToolCall",
    "ToolContext",
    "ToolDefinition",
    "ToolRegistry",
    "ToolSpec",
    "Turn",
    "Price",
    "Usage",
    "UsageEvent",
    "estimated_cost_micros",
    "UsageRecorder",
    "citations_as_text",
    "decide",
    "define_agent",
    "define_knowledge_source",
    "define_prompt",
    "define_tool",
    "is_alias",
    "may_decide",
    "metadata_for",
    "month_start",
    "visible_tools",
]
