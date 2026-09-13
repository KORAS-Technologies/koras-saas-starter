"""Agents: a model alias, instructions, and the tools it may propose.

An agent is configuration. It names the alias it answers with, the prompt
that instructs it, the tools it is allowed to ask for, and how many turns the
runtime will let it take before handing the conversation back. It holds no
credential, no provider name and no authority: the tools it names are still
checked against the caller's permissions when the model proposes one.

The starter ships one, the reference assistant, so the framework can be
exercised. A product defines its own in its extension point and replaces or
extends that one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .errors import AIError, ErrorCode, invalid_alias, not_found
from .models import is_alias

_AGENT_ID = re.compile(r"^[a-z][a-z0-9-]*$")


class Capability(StrEnum):
    CHAT = "chat"
    TOOLS = "tools"
    RETRIEVAL = "retrieval"


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    #: A model alias. Never a provider model name.
    model: str
    #: The system instructions, or the id of a registered prompt when
    #: `prompt_id` is set instead.
    instructions: str = ""
    prompt_id: str | None = None
    capabilities: frozenset[Capability] = frozenset({Capability.CHAT})
    tools: tuple[str, ...] = ()
    #: Model calls per user message before the runtime stops and answers with
    #: what it has. A loop that could not end is a bill that could not end.
    max_turns: int = 4
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not _AGENT_ID.match(self.id):
            raise ValueError(f"agent id {self.id!r} must be lower-case, like sample-assistant")
        if not is_alias(self.model):
            raise invalid_alias(self.model)
        if not self.instructions.strip() and not self.prompt_id:
            raise ValueError(f"agent {self.id} needs instructions or a prompt id")
        if self.tools and Capability.TOOLS not in self.capabilities:
            raise ValueError(f"agent {self.id} names tools but lacks the tools capability")
        if self.max_turns < 1 or self.max_turns > 16:
            raise ValueError(f"agent {self.id} max_turns must be between 1 and 16")

    def may_use_tools(self) -> bool:
        return Capability.TOOLS in self.capabilities and bool(self.tools)


def define_agent(
    *,
    id: str,
    name: str,
    model: str,
    instructions: str = "",
    prompt_id: str | None = None,
    capabilities: Iterable[Capability | str] = (Capability.CHAT,),
    tools: Iterable[str] = (),
    max_turns: int = 4,
    temperature: float | None = None,
) -> AgentDefinition:
    return AgentDefinition(
        id=id,
        name=name,
        model=model,
        instructions=instructions,
        prompt_id=prompt_id,
        capabilities=frozenset(Capability(value) for value in capabilities),
        tools=tuple(tools),
        max_turns=max_turns,
        temperature=temperature,
    )


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def add(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.id in self._agents:
            raise ValueError(f"agent {agent.id} is already registered")
        self._agents[agent.id] = agent
        return agent

    def get(self, agent_id: str) -> AgentDefinition:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise not_found("agent")
        return agent

    def default(self) -> AgentDefinition:
        """The first registered agent, which is what a conversation with no
        agent named runs as."""
        if not self._agents:
            raise AIError(ErrorCode.CONFIGURATION_ERROR, "no agent is registered")
        return next(iter(self._agents.values()))

    def ids(self) -> tuple[str, ...]:
        return tuple(self._agents)
