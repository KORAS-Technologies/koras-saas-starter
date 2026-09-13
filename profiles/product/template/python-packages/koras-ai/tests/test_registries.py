"""Tools, agents, prompts and knowledge sources: what a definition refuses."""

from __future__ import annotations

import pytest
from koras_ai import (
    AgentRegistry,
    AIError,
    Chunk,
    Document,
    ErrorCode,
    KnowledgeRegistry,
    ModelAlias,
    Operation,
    PromptRegistry,
    RetrievalScope,
    SimpleChunker,
    ToolContext,
    ToolRegistry,
    define_agent,
    define_knowledge_source,
    define_prompt,
    define_tool,
)
from pydantic import BaseModel


class _Input(BaseModel):
    name: str


async def _noop(ctx: ToolContext, input: _Input) -> str:
    return input.name


# ── tools ─────────────────────────────────────────────────────────────────────


def test_a_tool_id_is_dotted_lower_case() -> None:
    with pytest.raises(ValueError, match="dotted"):
        define_tool(
            id="ListFiles",
            description="x",
            permission="files.read",
            operation=Operation.READ,
            input_model=_Input,
            execute=_noop,
        )


def test_a_tool_must_name_a_permission() -> None:
    with pytest.raises(ValueError, match="permission"):
        define_tool(
            id="files.list",
            description="x",
            permission=" ",
            operation=Operation.READ,
            input_model=_Input,
            execute=_noop,
        )


def test_approval_can_be_added_to_a_read_and_never_removed_from_a_write() -> None:
    cautious = define_tool(
        id="files.peek",
        description="x",
        permission="files.read",
        operation=Operation.READ,
        input_model=_Input,
        execute=_noop,
        approval=True,
    )
    assert cautious.requires_approval
    write = define_tool(
        id="files.touch",
        description="x",
        permission="files.manage",
        operation=Operation.WRITE,
        input_model=_Input,
        execute=_noop,
        approval=False,
    )
    assert write.requires_approval


def test_the_spec_carries_the_input_schema_and_parse_validates(tools: ToolRegistry) -> None:
    spec = tools.get("files.rename").spec()
    assert spec.name == "files.rename"
    assert "file_id" in spec.parameters["properties"]
    with pytest.raises(AIError) as refused:
        tools.get("files.rename").parse({"file_id": "x"})
    assert refused.value.code is ErrorCode.INVALID_INPUT


def test_an_unregistered_tool_is_refused_by_name(tools: ToolRegistry) -> None:
    with pytest.raises(AIError) as refused:
        tools.get("files.explode")
    assert refused.value.code is ErrorCode.UNREGISTERED_ACTION
    with pytest.raises(ValueError, match="already"):
        tools.add(tools.get("files.list"))


# ── agents ────────────────────────────────────────────────────────────────────


def test_an_agent_names_an_alias_and_not_a_model() -> None:
    with pytest.raises(AIError) as refused:
        define_agent(id="a", name="A", model="gpt-4o", instructions="x")
    assert refused.value.code is ErrorCode.INVALID_MODEL_ALIAS


def test_an_agent_with_tools_needs_the_tools_capability() -> None:
    with pytest.raises(ValueError, match="tools capability"):
        define_agent(
            id="a", name="A", model=ModelAlias.FAST, instructions="x", tools=("files.list",)
        )


def test_an_agent_needs_instructions_or_a_prompt() -> None:
    with pytest.raises(ValueError, match="instructions"):
        define_agent(id="a", name="A", model=ModelAlias.FAST)
    agent = define_agent(id="a", name="A", model=ModelAlias.FAST, prompt_id="assistant.system")
    assert agent.prompt_id == "assistant.system"


def test_the_default_agent_is_the_first_registered(agents: AgentRegistry) -> None:
    assert agents.default().id == "assistant"
    with pytest.raises(AIError) as refused:
        agents.get("nobody")
    assert refused.value.code is ErrorCode.NOT_FOUND


# ── prompts ───────────────────────────────────────────────────────────────────


def test_a_prompt_declares_exactly_the_variables_it_uses() -> None:
    with pytest.raises(ValueError, match="undeclared"):
        define_prompt(id="a.b", version=1, template="Hello {name}")
    prompt = define_prompt(id="a.b", version=1, template="Hello {name}", variables=["name"])
    assert prompt.render({"name": "Ada"}) == "Hello Ada"


def test_rendering_is_strict_both_ways() -> None:
    prompt = define_prompt(id="a.b", version=1, template="Hello {name}", variables=["name"])
    with pytest.raises(AIError):
        prompt.render({})
    with pytest.raises(AIError):
        prompt.render({"name": "Ada", "extra": 1})


def test_a_value_cannot_reach_into_the_template() -> None:
    prompt = define_prompt(id="a.b", version=1, template="Say {text}", variables=["text"])
    assert prompt.render({"text": "{name.__class__}"}) == "Say {name.__class__}"


def test_the_registry_answers_the_latest_version_unless_asked() -> None:
    registry = PromptRegistry()
    registry.add(define_prompt(id="a.b", version=1, template="one"))
    registry.add(define_prompt(id="a.b", version=2, template="two"))
    assert registry.render("a.b", {}) == "two"
    assert registry.render("a.b", {}, version=1) == "one"
    with pytest.raises(ValueError, match="already"):
        registry.add(define_prompt(id="a.b", version=2, template="again"))


# ── knowledge ─────────────────────────────────────────────────────────────────


def test_a_scope_needs_a_tenant() -> None:
    with pytest.raises(ValueError):
        RetrievalScope(tenant_id="", product_code="p")


def test_every_source_is_tenant_scoped() -> None:
    with pytest.raises(ValueError, match="tenant-scoped"):
        define_knowledge_source(id="docs", resource_type="document", tenant_scoped=False)
    registry = KnowledgeRegistry()
    registry.add(define_knowledge_source(id="docs", resource_type="document"))
    assert registry.for_resource("document")[0].id == "docs"
    assert registry.for_resource("matter") == ()


def test_the_chunker_windows_with_overlap() -> None:
    document = Document(
        id="d1",
        source_id="docs",
        tenant_id="t",
        resource_type="document",
        resource_id="1",
        title="T",
        text="abcdefghij",
    )
    chunks = SimpleChunker(size=4, overlap=1).chunk(document)
    assert [c.text for c in chunks] == ["abcd", "defg", "ghij"]
    assert all(isinstance(c, Chunk) and c.tenant_id == "t" for c in chunks)
