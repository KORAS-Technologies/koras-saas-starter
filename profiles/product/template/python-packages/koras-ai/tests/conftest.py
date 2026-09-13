"""Shared fixtures: callers, a catalogue, tools and an agent.

Two tenants and two callers, because the claims worth testing are about the
boundary: what tenant B cannot see of tenant A, and what a member cannot
approve that an owner can.
"""

from __future__ import annotations

from typing import Any

import pytest
from koras_ai import (
    AgentRegistry,
    AIContext,
    ModelAlias,
    ModelCatalogue,
    ModelRoute,
    Operation,
    ToolContext,
    ToolRegistry,
    define_agent,
    define_tool,
)
from pydantic import BaseModel
from support import MEMBER, context


@pytest.fixture
def owner_a() -> AIContext:
    return context()


@pytest.fixture
def member_a() -> AIContext:
    return context(user="member-a", roles=frozenset({"member"}), permissions=MEMBER)


@pytest.fixture
def owner_b() -> AIContext:
    return context(tenant="tenant-b", user="user-b")


@pytest.fixture
def catalogue() -> ModelCatalogue:
    return ModelCatalogue(
        {
            ModelAlias.FAST: [
                ModelRoute("openai", "gpt-mini"),
                ModelRoute("anthropic", "claude-mini"),
            ],
            ModelAlias.BALANCED: [
                ModelRoute("openai", "gpt-4o"),
                ModelRoute("anthropic", "claude"),
            ],
            ModelAlias.EMBEDDING: [ModelRoute("openai", "embed-small")],
        }
    )


class ListInput(BaseModel):
    limit: int = 10


class DeleteInput(BaseModel):
    file_id: str


class RenameInput(BaseModel):
    file_id: str
    name: str


async def _list(ctx: ToolContext, args: ListInput) -> dict[str, Any]:
    return {"tenant": ctx.context.tenant_id, "files": ["a.pdf", "b.pdf"][: args.limit]}


async def _delete(ctx: ToolContext, args: DeleteInput) -> dict[str, Any]:
    return {"deleted": args.file_id}


async def _rename(ctx: ToolContext, args: RenameInput) -> dict[str, Any]:
    return {"renamed": args.file_id, "to": args.name}


@pytest.fixture
def tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        define_tool(
            id="files.list",
            description="List the files in this organization",
            permission="files.read",
            operation=Operation.READ,
            input_model=ListInput,
            execute=_list,
        )
    )
    registry.add(
        define_tool(
            id="files.rename",
            description="Rename a file",
            permission="files.manage",
            operation=Operation.WRITE,
            input_model=RenameInput,
            execute=_rename,
        )
    )
    registry.add(
        define_tool(
            id="files.delete",
            description="Delete a file",
            permission="files.manage",
            operation=Operation.DESTRUCTIVE,
            input_model=DeleteInput,
            execute=_delete,
        )
    )
    return registry


@pytest.fixture
def agents() -> AgentRegistry:
    registry = AgentRegistry()
    registry.add(
        define_agent(
            id="assistant",
            name="Assistant",
            model=ModelAlias.BALANCED,
            instructions="You help with files.",
            capabilities=("chat", "tools"),
            tools=("files.list", "files.rename", "files.delete"),
            max_turns=3,
        )
    )
    return registry
