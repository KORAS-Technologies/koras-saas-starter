"""The context refuses to be empty, and the policy decides from it alone."""

from __future__ import annotations

import pytest
from koras_ai import (
    AIContext,
    Operation,
    PageContext,
    ToolRegistry,
    decide,
    may_decide,
    visible_tools,
)
from support import ALL, MEMBER, context


def test_a_context_needs_every_identity_field() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        AIContext(
            product_code="p",
            environment="dev",
            tenant_id=" ",
            organization_id="o",
            user_id="u",
            roles=frozenset(),
            permissions=frozenset(),
        )


def test_a_page_context_needs_both_halves() -> None:
    with pytest.raises(ValueError):
        PageContext(type="document", id="")
    assert PageContext(type="document", id="42").id == "42"


def test_a_read_runs_for_anyone_holding_the_permission(tools: ToolRegistry) -> None:
    decision = decide(tools.get("files.list"), context(permissions=MEMBER))
    assert decision.allowed and not decision.requires_approval


def test_a_write_waits_for_a_person(tools: ToolRegistry) -> None:
    decision = decide(tools.get("files.rename"), context(permissions=ALL))
    assert decision.allowed and decision.requires_approval


def test_a_missing_permission_is_refused_without_naming_it(tools: ToolRegistry) -> None:
    decision = decide(tools.get("files.rename"), context(permissions=MEMBER))
    assert not decision.allowed
    assert "files.manage" not in decision.reason or "lacks" in decision.reason


def test_a_caller_without_ai_use_gets_nothing(tools: ToolRegistry) -> None:
    decision = decide(tools.get("files.list"), context(permissions=frozenset({"files.read"})))
    assert not decision.allowed


def test_approving_needs_the_approve_permission_and_the_tools_own(tools: ToolRegistry) -> None:
    assert not may_decide(tools.get("files.rename"), context(permissions=MEMBER)).allowed
    only_approve = frozenset({"ai.use", "ai.approve"})
    assert not may_decide(tools.get("files.rename"), context(permissions=only_approve)).allowed
    assert may_decide(tools.get("files.rename"), context(permissions=ALL)).allowed


def test_a_destructive_action_needs_an_owner_or_administrator(tools: ToolRegistry) -> None:
    security = context(roles=frozenset({"security_admin"}), permissions=ALL)
    assert not may_decide(tools.get("files.delete"), security).allowed
    owner = context(roles=frozenset({"organization_owner"}), permissions=ALL)
    assert may_decide(tools.get("files.delete"), owner).allowed


def test_the_model_is_only_shown_tools_the_caller_may_use(tools: ToolRegistry) -> None:
    every = tuple(tools.get(tool_id) for tool_id in tools.ids())
    shown = visible_tools(every, context(permissions=MEMBER), tools_enabled=True)
    assert [t.id for t in shown] == ["files.list"]
    assert visible_tools(every, context(permissions=ALL), tools_enabled=False) == ()
    assert tools.get("files.delete").operation is Operation.DESTRUCTIVE
