"""The turn, the approvals, the meter and the tenant boundary, end to end.

Every test drives the runtime the way the API will: a context built by hand,
a fake provider that proposes what the test needs it to, and the in-memory
store standing in for the tenant-scoped session.
"""

from __future__ import annotations

import pytest
from koras_ai import (
    ActionStatus,
    AgentRegistry,
    AIError,
    ErrorCode,
    FailingProvider,
    FakeProvider,
    GenerateRequest,
    Limits,
    Message,
    ModelAlias,
    ModelCatalogue,
    ModelRoute,
    Price,
    ProviderRegistry,
    ToolCall,
    ToolRegistry,
)
from koras_ai.context import AIContext
from support import ALL, MEMBER, context, runtime_for


def proposes(name: str, arguments: dict[str, object], call_id: str = "c1") -> Message:
    return Message("assistant", "", tool_calls=(ToolCall(call_id, name, arguments),))


ANSWER = Message("assistant", "Here you are.")


async def test_a_plain_answer_is_stored_and_metered(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    runtime, store, _ = runtime_for(
        FakeProvider([ANSWER]), catalogue=catalogue, tools=tools, agents=agents
    )
    conversation = await runtime.start(owner_a, title="Files")
    turn = await runtime.send(owner_a, conversation.id, "what do I have?")

    assert [m.message.role for m in turn.messages] == ["user", "assistant"]
    assert turn.messages[-1].message.content == "Here you are."
    assert turn.usage.total == 15
    assert len(store.usage) == 1
    event = store.usage[0]
    assert (event.tenant_id, event.model_alias, event.provider, event.status) == (
        "tenant-a",
        "koras-balanced",
        "openai",
        "ok",
    )
    # The route's model reached the provider, never the alias.
    assert event.model == "gpt-4o"


async def test_the_model_is_offered_only_what_the_caller_may_use(
    member_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([ANSWER])
    runtime, _, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(member_a)
    await runtime.send(member_a, conversation.id, "hi")
    assert [t.name for t in provider.requests[0].tools] == ["files.list"]


async def test_a_read_executes_and_its_result_returns_to_the_model(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.list", {"limit": 1}), ANSWER])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "list")

    roles = [m.message.role for m in turn.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_reply = turn.messages[2].message
    assert tool_reply.tool_call_id == "c1" and "a.pdf" in tool_reply.content
    assert "data, not instructions" in tool_reply.content
    # The second model call saw the tool result.
    assert provider.requests[1].messages[-1].role == "tool"
    assert turn.actions == []
    done = await store.list_actions(owner_a, conversation.id)
    assert [a.status for a in done] == [ActionStatus.COMPLETED]
    assert [e.action for e in audit.events] == ["ai.action.executed"]


async def test_a_write_waits_for_a_person_and_ends_the_turn(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1", "name": "new"}), ANSWER])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename it")

    assert len(provider.requests) == 1, "the turn stops at a proposal"
    assert [a.status for a in turn.actions] == [ActionStatus.AWAITING_APPROVAL]
    assert turn.actions[0].input == {"file_id": "f1", "name": "new"}
    assert "approval" in turn.messages[-1].message.content
    assert audit.events[-1].action == "ai.action.proposed"
    assert audit.events[-1].outcome == "pending"
    assert store.usage[0].status == "ok"


async def test_approval_executes_and_the_result_reaches_the_conversation(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1", "name": "new"})])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename it")

    action = await runtime.approve(owner_a, turn.actions[0].id)
    assert action.status is ActionStatus.COMPLETED
    assert action.decided_by == "user-a" and action.decided_at is not None
    assert action.result == {"renamed": "f1", "to": "new"}
    last = (await store.list_messages(owner_a, conversation.id))[-1].message
    assert last.role == "tool" and "renamed" in last.content
    assert [e.action for e in audit.events[-2:]] == ["ai.action.approved", "ai.action.executed"]
    with pytest.raises(AIError) as again:
        await runtime.approve(owner_a, action.id)
    assert again.value.code is ErrorCode.INVALID_STATE


async def test_rejection_is_recorded_and_told_to_the_model(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1", "name": "new"})])
    runtime, store, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename it")
    action = await runtime.reject(owner_a, turn.actions[0].id)
    assert action.status is ActionStatus.REJECTED
    assert "declined" in (await store.list_messages(owner_a, conversation.id))[-1].message.content


async def test_a_member_cannot_approve_what_they_could_not_do(
    owner_a: AIContext,
    member_a: AIContext,
    catalogue: ModelCatalogue,
    tools: ToolRegistry,
    agents: AgentRegistry,
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1", "name": "new"})])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename it")

    with pytest.raises(AIError) as refused:
        await runtime.approve(member_a, turn.actions[0].id)
    assert refused.value.code is ErrorCode.TOOL_DENIED
    assert "files.manage" not in refused.value.message
    still = await store.get_action(owner_a, turn.actions[0].id)
    assert still is not None and still.status is ActionStatus.AWAITING_APPROVAL
    assert audit.events[-1].outcome == "denied"


async def test_a_destructive_action_needs_an_administrator_to_approve(
    catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    # Holds every permission, including approve, but is a security admin: the
    # permission is not enough for a destructive operation.
    security = context(user="sec", roles=frozenset({"security_admin"}), permissions=ALL)
    owner = context()
    provider = FakeProvider([proposes("files.delete", {"file_id": "f1"})])
    runtime, _, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(security)
    turn = await runtime.send(security, conversation.id, "delete it")

    with pytest.raises(AIError):
        await runtime.approve(security, turn.actions[0].id)
    done = await runtime.approve(owner, turn.actions[0].id)
    assert done.status is ActionStatus.COMPLETED


async def test_a_tool_the_caller_may_not_use_is_refused_even_if_proposed(
    member_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    # The model was not offered it and proposed it anyway. The refusal is
    # deterministic and the audit says so; no action row is created.
    provider = FakeProvider([proposes("files.delete", {"file_id": "f1"}), ANSWER])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(member_a)
    turn = await runtime.send(member_a, conversation.id, "delete everything")

    assert turn.actions == []
    assert "not available" in turn.messages[2].message.content
    assert await store.list_actions(member_a, conversation.id) == []
    assert audit.events[0].outcome == "denied"


async def test_an_unregistered_tool_is_refused_by_name(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("shell.exec", {"cmd": "rm -rf /"}), ANSWER])
    runtime, store, audit = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "run this")
    assert "shell.exec is not available" in turn.messages[2].message.content
    assert await store.list_actions(owner_a, conversation.id) == []
    assert audit.events[0].details["reason"] == "unregistered or not offered"


async def test_invalid_arguments_are_refused_before_anything_runs(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1"}), ANSWER])
    runtime, store, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename")
    assert "not valid" in turn.messages[2].message.content
    assert await store.list_actions(owner_a, conversation.id) == []


async def test_tools_can_be_switched_off_by_the_plan(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([ANSWER])
    runtime, _, _ = runtime_for(
        provider,
        catalogue=catalogue,
        tools=tools,
        agents=agents,
        limits=Limits(tools_enabled=False),
    )
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "hi")
    assert provider.requests[0].tools == ()


async def test_the_monthly_allowance_is_enforced_on_successful_calls(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([ANSWER, ANSWER, ANSWER])
    runtime, _, _ = runtime_for(
        provider, catalogue=catalogue, tools=tools, agents=agents, limits=Limits(monthly_requests=2)
    )
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "one")
    await runtime.send(owner_a, conversation.id, "two")
    with pytest.raises(AIError) as refused:
        await runtime.send(owner_a, conversation.id, "three")
    assert refused.value.code is ErrorCode.USAGE_EXCEEDED
    status = await runtime.status(owner_a)
    assert (status.requests_this_month, status.monthly_limit) == (2, 2)
    assert status.over_allowance is False and status.billable_this_month_micros == 0


async def test_the_turn_limit_stops_a_model_that_keeps_asking(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    always = [proposes("files.list", {}, f"c{n}") for n in range(10)]
    provider = FakeProvider(always)
    runtime, _, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "loop")
    assert len(provider.requests) == 3  # the agent's max_turns


async def test_a_failing_route_falls_back_and_both_attempts_are_metered(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    down = FailingProvider(AIError(ErrorCode.PROVIDER_UNAVAILABLE, "down"))
    up = FakeProvider([ANSWER])
    runtime, store, _ = runtime_for(up, catalogue=catalogue, tools=tools, agents=agents)
    providers = ProviderRegistry()
    providers.register("openai", down)
    providers.register("anthropic", up)
    runtime.providers = providers

    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "hi")
    assert turn.messages[-1].message.content == "Here you are."
    assert [(e.provider, e.status) for e in store.usage] == [
        ("openai", "error"),
        ("anthropic", "ok"),
    ]
    assert store.usage[0].error_code == "provider_unavailable"


async def test_a_credential_refusal_does_not_fall_back(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    refused = FailingProvider(AIError(ErrorCode.CONFIGURATION_ERROR, "bad key"))
    up = FakeProvider([ANSWER])
    runtime, _, _ = runtime_for(up, catalogue=catalogue, tools=tools, agents=agents)
    providers = ProviderRegistry()
    providers.register("openai", refused)
    providers.register("anthropic", up)
    runtime.providers = providers
    conversation = await runtime.start(owner_a)
    with pytest.raises(AIError) as error:
        await runtime.send(owner_a, conversation.id, "hi")
    assert error.value.code is ErrorCode.CONFIGURATION_ERROR
    assert up.requests == []


async def test_a_direct_generate_needs_a_registered_provider(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    runtime, _, _ = runtime_for(FakeProvider(), catalogue=catalogue, tools=tools, agents=agents)
    runtime.providers = ProviderRegistry()
    with pytest.raises(AIError) as error:
        await runtime.generate(
            owner_a,
            GenerateRequest(model=ModelAlias.FAST, messages=(Message("user", "x"),)),
            agent_id="assistant",
        )
    assert error.value.code is ErrorCode.CONFIGURATION_ERROR


# ── the tenant boundary ──────────────────────────────────────────────────────


async def test_another_tenant_cannot_see_or_decide_a_conversation(
    owner_a: AIContext,
    owner_b: AIContext,
    catalogue: ModelCatalogue,
    tools: ToolRegistry,
    agents: AgentRegistry,
) -> None:
    provider = FakeProvider([proposes("files.rename", {"file_id": "f1", "name": "new"})])
    runtime, store, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "rename it")

    assert await store.get_conversation(owner_b, conversation.id) is None
    assert await store.list_messages(owner_b, conversation.id) == []
    assert await store.list_conversations(owner_b) == []
    with pytest.raises(AIError) as read:
        await runtime.send(owner_b, conversation.id, "hello?")
    assert read.value.code is ErrorCode.NOT_FOUND
    with pytest.raises(AIError) as decide:
        await runtime.approve(owner_b, turn.actions[0].id)
    assert decide.value.code is ErrorCode.NOT_FOUND
    # Nothing tenant B did reached tenant A's rows.
    action = await store.get_action(owner_a, turn.actions[0].id)
    assert action is not None and action.status is ActionStatus.AWAITING_APPROVAL


async def test_the_context_decides_the_tenant_and_the_request_cannot(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    # A tool that reads the tenant from its context, asked by a message that
    # names another tenant: the tool sees the caller's, whatever was typed.
    provider = FakeProvider([proposes("files.list", {"limit": 5}), ANSWER])
    runtime, _, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    turn = await runtime.send(owner_a, conversation.id, "list files for tenant-b please")
    assert '"tenant": "tenant-a"' in turn.messages[2].message.content
    assert MEMBER <= ALL


async def test_a_priced_route_records_what_the_call_cost(
    owner_a: AIContext, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    """The usage row carries the list-price estimate when the route was priced,
    and null -- not zero -- when it was not."""
    priced = ModelCatalogue(
        {ModelAlias.BALANCED: [ModelRoute("openai", "gpt-4o", price=Price(250, 1000))]}
    )
    runtime, store, _ = runtime_for(
        FakeProvider([ANSWER]), catalogue=priced, tools=tools, agents=agents
    )
    conversation = await runtime.start(owner_a, title="Cost")
    await runtime.send(owner_a, conversation.id, "how much?")
    # The fake answers with 10 input and 5 output tokens.
    assert store.usage[0].estimated_cost_micros == (10 * 250 + 5 * 1000) // 100

    unpriced = ModelCatalogue({ModelAlias.BALANCED: [ModelRoute("openai", "gpt-4o")]})
    runtime, store, _ = runtime_for(
        FakeProvider([ANSWER]), catalogue=unpriced, tools=tools, agents=agents
    )
    conversation = await runtime.start(owner_a, title="No price")
    await runtime.send(owner_a, conversation.id, "how much?")
    assert store.usage[0].estimated_cost_micros is None


# ── the turn as events ─────────────────────────────────────────────────────


async def test_a_turn_can_be_followed_as_it_happens(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    runtime, store, _ = runtime_for(
        FakeProvider([ANSWER]), catalogue=catalogue, tools=tools, agents=agents
    )
    conversation = await runtime.start(owner_a, title="Files")
    events = [e async for e in runtime.stream(owner_a, conversation.id, "what do I have?")]

    assert [e.kind for e in events] == ["message", "delta", "message", "done"]
    assert events[0].message is not None and events[0].message.message.role == "user"
    assert events[1].text == "Here you are."
    assert events[2].message is not None and events[2].message.message.content == "Here you are."
    turn = events[3].turn
    assert turn is not None
    assert [m.message.role for m in turn.messages] == ["user", "assistant"]
    assert turn.usage.total == 15
    # Metered once, as a whole turn is; and the store holds what was announced.
    assert len(store.usage) == 1
    stored = await store.list_messages(owner_a, conversation.id)
    assert [m.id for m in stored] == [m.id for m in turn.messages]


async def test_a_parked_action_is_announced_when_it_is_parked(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([proposes("files.delete", {"file_id": "f1"})])
    runtime, _, _ = runtime_for(provider, catalogue=catalogue, tools=tools, agents=agents)
    conversation = await runtime.start(owner_a)
    events = [e async for e in runtime.stream(owner_a, conversation.id, "delete f1")]

    assert [e.kind for e in events] == ["message", "message", "message", "action", "done"]
    action = events[3].action
    assert action is not None and action.tool_id == "files.delete"
    assert action.status is ActionStatus.AWAITING_APPROVAL
    turn = events[4].turn
    assert turn is not None and [a.id for a in turn.actions] == [action.id]


async def test_a_route_that_fails_before_speaking_is_abandoned_for_the_next(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    from koras_ai import AIConfiguration, AIRuntime, InMemoryStore, PromptRegistry, StaticRouting
    from koras_audit import MemoryAuditSink

    providers = ProviderRegistry()
    providers.register("openai", FailingProvider(AIError(ErrorCode.PROVIDER_UNAVAILABLE, "down")))
    providers.register("anthropic", FakeProvider([ANSWER]))
    memory = InMemoryStore()
    runtime = AIRuntime(
        configuration=AIConfiguration(
            catalogue=catalogue, routing=StaticRouting(), fail_closed=False, limits=Limits()
        ),
        providers=providers,
        tools=tools,
        agents=agents,
        prompts=PromptRegistry(),
        store=memory,
        usage=memory,
        audit=MemoryAuditSink(),
    )
    conversation = await runtime.start(owner_a)
    events = [e async for e in runtime.stream(owner_a, conversation.id, "hi")]

    assert [e.kind for e in events] == ["message", "delta", "message", "done"]
    # Both attempts are on the meter: the one that failed and the one that answered.
    assert [(e.provider, e.status) for e in memory.usage] == [
        ("openai", "error"),
        ("anthropic", "ok"),
    ]


# ── pay as you go ──────────────────────────────────────────────────────────


def _priced(catalogue: ModelCatalogue) -> ModelCatalogue:
    """The same catalogue with a price on the balanced route, so a call costs."""
    return catalogue


async def test_a_failed_call_does_not_spend_the_allowance(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    providers = ProviderRegistry()
    providers.register("openai", FailingProvider(AIError(ErrorCode.PROVIDER_UNAVAILABLE, "down")))
    providers.register("anthropic", FakeProvider([ANSWER, ANSWER]))
    from koras_ai import AIConfiguration, AIRuntime, InMemoryStore, PromptRegistry, StaticRouting
    from koras_audit import MemoryAuditSink

    memory = InMemoryStore()
    runtime = AIRuntime(
        configuration=AIConfiguration(
            catalogue=catalogue,
            routing=StaticRouting(),
            fail_closed=False,
            limits=Limits(monthly_requests=2),
        ),
        providers=providers,
        tools=tools,
        agents=agents,
        prompts=PromptRegistry(),
        store=memory,
        usage=memory,
        audit=MemoryAuditSink(),
    )
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "one")
    await runtime.send(owner_a, conversation.id, "two")
    # Four rows -- two failures, two answers -- and two of the allowance used.
    assert [e.status for e in memory.usage] == ["error", "ok", "error", "ok"]
    assert (await runtime.status(owner_a)).requests_this_month == 2


async def test_past_the_allowance_with_pay_as_you_go_the_call_is_made_and_stamped(
    owner_a: AIContext, catalogue: ModelCatalogue, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    provider = FakeProvider([ANSWER, ANSWER, ANSWER])
    runtime, store, _ = runtime_for(
        provider,
        catalogue=catalogue,
        tools=tools,
        agents=agents,
        limits=Limits(monthly_requests=1, overage_enabled=True, overage_rate_percent=400),
    )
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "inside")
    turn = await runtime.send(owner_a, conversation.id, "beyond")
    assert turn.messages[-1].message.content == "Here you are."

    inside, beyond = store.usage
    assert inside.over_allowance is False and inside.billable_micros is None
    assert beyond.over_allowance is True and beyond.overage_rate_percent == 400
    # Priced routes are stamped at four times cost; this catalogue has no prices,
    # so the call is beyond the allowance and billable at nothing -- flagged,
    # never silently charged at a made-up number.
    assert (
        beyond.billable_micros is None
        if beyond.estimated_cost_micros is None
        else (beyond.billable_micros == beyond.estimated_cost_micros * 4)
    )
    status = await runtime.status(owner_a)
    assert status.over_allowance is True and status.overage_enabled is True


async def test_the_pay_as_you_go_limit_is_the_stop(
    owner_a: AIContext, tools: ToolRegistry, agents: AgentRegistry
) -> None:
    priced = ModelCatalogue(
        {
            ModelAlias.FAST: [ModelRoute("openai", "gpt-mini", price=Price(100, 100))],
            ModelAlias.BALANCED: [ModelRoute("openai", "gpt-4o", price=Price(100, 100))],
            ModelAlias.EMBEDDING: [ModelRoute("openai", "embed-small")],
        }
    )
    provider = FakeProvider([ANSWER, ANSWER, ANSWER])
    runtime, store, _ = runtime_for(
        provider,
        catalogue=priced,
        tools=tools,
        agents=agents,
        # 15 tokens at 100 cents per million is 15 micro-dollars; times four is 60.
        limits=Limits(
            monthly_requests=1,
            overage_enabled=True,
            overage_rate_percent=400,
            overage_cap_micros=60,
        ),
    )
    conversation = await runtime.start(owner_a)
    await runtime.send(owner_a, conversation.id, "inside")
    await runtime.send(owner_a, conversation.id, "beyond, charged")
    assert store.usage[-1].billable_micros == 60
    with pytest.raises(AIError) as refused:
        await runtime.send(owner_a, conversation.id, "beyond the limit")
    assert refused.value.code is ErrorCode.USAGE_EXCEEDED
    assert "pay-as-you-go limit" in refused.value.message
    status = await runtime.status(owner_a)
    assert status.billable_this_month_micros == 60 and status.overage_cap_micros == 60
