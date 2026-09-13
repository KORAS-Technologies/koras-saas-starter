"""The request and result shapes every provider speaks.

Frozen dataclasses rather than pydantic models: these cross no trust boundary
-- the router validates its own request bodies with pydantic before anything
here is built -- and a frozen value is what a conversation history should be
made of.

`Usage` counts are named `input`, `output` and `total`. The API's response
models carry the same names, and the API's security test refuses any response
field whose name contains the word "token". A count of tokens is not a token,
but a rule that reads names cannot tell, and the names here are chosen so the
runtime, the wire and the page all say the same thing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked to run, with the arguments it proposed.

    Proposed, not authorised: the runtime decides whether this executes.
    """

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    #: Set on a `tool` message: which call this answers.
    tool_call_id: str | None = None
    #: Set on a `tool` message: which tool answered.
    name: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about a tool: a name, a sentence, a JSON schema."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    total: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            total=self.total + other.total,
        )


@dataclass(frozen=True)
class GenerateRequest:
    #: A model alias, never a provider model name. Resolved by the runtime.
    model: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    temperature: float | None = None
    max_output: int | None = None
    #: Dimensions for the provider's own logs. Never content, never identity
    #: beyond what the caller chose to put here.
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerateResult:
    message: Message
    usage: Usage
    #: The provider and model that actually answered, for the usage record.
    provider: str
    model: str
    latency_ms: int
    finish_reason: str = "stop"


@dataclass(frozen=True)
class GenerateEvent:
    """One event of a streamed generation.

    `delta` carries text; `tool_call` carries a complete proposed call once
    its arguments have all arrived; `done` carries the assembled result.
    """

    kind: Literal["delta", "tool_call", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    result: GenerateResult | None = None


@dataclass(frozen=True)
class EmbedRequest:
    model: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class EmbedResult:
    vectors: tuple[tuple[float, ...], ...]
    usage: Usage
    provider: str
    model: str
