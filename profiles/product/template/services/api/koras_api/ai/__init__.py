"""This product's AI: its agents, tools, prompts, knowledge sources and models.

The extension point. `koras_ai` is the framework and this package is what the
product declares on top of it. The API's dependency reads `registries` from
here and nowhere else, so adding an agent is adding it to `agents.py`, adding
a tool is adding it to `tools.py`, and the runtime sees both at the next
process start.

What ships is a reference: one assistant that can list the tenant's files,
enough to prove the framework end to end and small enough to replace. A
product's own agents, tools and prompts belong here beside it -- and its
domain never belongs in `koras_ai`, which is the platform's.

Registries are built once at import and are immutable thereafter: a tool
registered per request would be a tool that exists for some callers and not
others, and an audit trail nobody could read back.
"""

from __future__ import annotations

from dataclasses import dataclass

from koras_ai import (
    AgentRegistry,
    KnowledgeRegistry,
    ModelCatalogue,
    PromptRegistry,
    ToolRegistry,
)

from . import agents as _agents
from . import knowledge as _knowledge
from . import models as _models
from . import prompts as _prompts
from . import tools as _tools


@dataclass(frozen=True)
class Registries:
    catalogue: ModelCatalogue
    #: The provider names in the platform's routing vocabulary that the
    #: gateway serves. A policy naming any other provider is skipped.
    PROVIDER_NAMES: tuple[str, ...]
    tools: ToolRegistry
    agents: AgentRegistry
    prompts: PromptRegistry
    knowledge: KnowledgeRegistry


def build() -> Registries:
    tools = ToolRegistry()
    for tool in _tools.TOOLS:
        tools.add(tool)

    prompts = PromptRegistry()
    for prompt in _prompts.PROMPTS:
        prompts.add(prompt)

    agents = AgentRegistry()
    for agent in _agents.AGENTS:
        # An agent naming a tool nobody registered would propose nothing and
        # look like a model that never uses tools. Refused at startup instead.
        for tool_id in agent.tools:
            tools.get(tool_id)
        if agent.prompt_id is not None:
            prompts.get(agent.prompt_id)
        agents.add(agent)

    knowledge = KnowledgeRegistry()
    for source in _knowledge.SOURCES:
        knowledge.add(source)

    return Registries(
        catalogue=_models.CATALOGUE,
        PROVIDER_NAMES=_models.PROVIDER_NAMES,
        tools=tools,
        agents=agents,
        prompts=prompts,
        knowledge=knowledge,
    )


registries = build()

__all__ = ["Registries", "build", "registries"]
