"""The agents this product offers.

One reference agent: the assistant, answering under the balanced alias with
the system prompt in `prompts.py` and the one read tool in `tools.py`. A
product replaces or extends this list; the first agent listed is the one a
conversation runs as when none is named.
"""

from __future__ import annotations

from koras_ai import AgentDefinition, ModelAlias, define_agent

AGENTS: tuple[AgentDefinition, ...] = (
    define_agent(
        id="assistant",
        name="Assistant",
        model=ModelAlias.BALANCED,
        prompt_id="assistant.system",
        capabilities=("chat", "tools"),
        tools=("files.list",),
        max_turns=4,
    ),
)
