"""Tools: what a model may ask to have done, declared by the product.

A tool is a registered, typed, permissioned operation. The model sees its
name, a sentence and a JSON schema; the runtime sees the permission it needs,
the class of operation it is, and the function that performs it. Every tool
call the model proposes is looked up here first, validated against the
schema second, and authorised third -- in code, against the caller's
verified permissions. A call for a name that is not registered is refused
as an unregistered action, whatever the model said.

Operation classes and their default policy:

    READ         permitted when the caller holds the permission; executes at once
    WRITE        requires the permission and a person's approval
    DESTRUCTIVE  requires the permission, approval, and an owner or administrator
    EXTERNAL     requires the permission and approval; leaves the product

A tool may opt into approval it would not otherwise need. It may not opt out:
a write that executes on a model's say-so is the failure this whole layer
exists to prevent, and there is no parameter for it.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from .context import AIContext
from .errors import AIError, ErrorCode, unregistered
from .types import ToolSpec

_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class Operation(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


#: The classes that never execute without a person.
NEEDS_APPROVAL = frozenset({Operation.WRITE, Operation.DESTRUCTIVE, Operation.EXTERNAL})


@dataclass(frozen=True)
class ToolContext:
    """What a tool's `execute` is handed.

    `context` is who and which tenant. `session` is the tenant-scoped database
    session the API opened for this request, or None where there is none.
    `services` is whatever the product chose to make reachable by name -- an
    object store, an HTTP client -- so a tool never constructs a credentialed
    client of its own.
    """

    context: AIContext
    session: Any | None = None
    services: Mapping[str, Any] = field(default_factory=dict)


ToolExecutor = Callable[[ToolContext, Any], Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    description: str
    #: The product permission the caller must hold. The permission vocabulary
    #: is the product's; this package only compares strings.
    permission: str
    operation: Operation
    #: The pydantic model the proposed arguments are validated against.
    input_model: type[BaseModel]
    execute: ToolExecutor
    #: True forces approval for a read. Never lowers what the operation needs.
    approval: bool = False

    def __post_init__(self) -> None:
        if not _TOOL_ID.match(self.id):
            raise ValueError(f"tool id {self.id!r} must be dotted lower-case, like files.list")
        if not self.description.strip():
            raise ValueError(f"tool {self.id} needs a description the model can read")
        if not self.permission.strip():
            raise ValueError(f"tool {self.id} must name the permission it needs")

    @property
    def requires_approval(self) -> bool:
        return self.approval or self.operation in NEEDS_APPROVAL

    def spec(self) -> ToolSpec:
        """What the model is shown. The schema is the input model's own."""
        return ToolSpec(
            name=self.id,
            description=self.description,
            parameters=self.input_model.model_json_schema(),
        )

    def parse(self, arguments: Mapping[str, Any]) -> BaseModel:
        """The model's proposal, validated. A bad proposal is invalid input."""
        try:
            return self.input_model.model_validate(dict(arguments))
        except ValidationError as error:
            raise AIError(
                ErrorCode.INVALID_INPUT,
                f"the arguments proposed for {self.id} are not valid",
                detail=str(error)[:500],
            ) from error


def define_tool(
    *,
    id: str,
    description: str,
    permission: str,
    operation: Operation,
    input_model: type[BaseModel],
    execute: ToolExecutor,
    approval: bool = False,
) -> ToolDefinition:
    """A tool, as a product declares one. Registered separately, on purpose:
    a definition is a value, and a registry is where a process keeps them."""
    return ToolDefinition(
        id=id,
        description=description,
        permission=permission,
        operation=operation,
        input_model=input_model,
        execute=execute,
        approval=approval,
    )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def add(self, tool: ToolDefinition) -> ToolDefinition:
        if tool.id in self._tools:
            raise ValueError(f"tool {tool.id} is already registered")
        self._tools[tool.id] = tool
        return tool

    def get(self, tool_id: str) -> ToolDefinition:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise unregistered(tool_id)
        return tool

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
