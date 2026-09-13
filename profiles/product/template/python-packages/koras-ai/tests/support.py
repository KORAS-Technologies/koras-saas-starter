"""Builders the tests share: a context per caller, a runtime around a fake provider.

A plain module rather than fixtures, so a test can build a second caller or a
second tenant inline where the contrast is the point.
"""

from __future__ import annotations

from koras_ai import (
    AgentRegistry,
    AIConfiguration,
    AIContext,
    AIRuntime,
    FakeProvider,
    InMemoryStore,
    Limits,
    ModelCatalogue,
    PromptRegistry,
    ProviderRegistry,
    StaticRouting,
    ToolRegistry,
)
from koras_audit import MemoryAuditSink

ALL = frozenset({"product.access", "files.read", "files.manage", "ai.use", "ai.approve"})
MEMBER = frozenset({"product.access", "files.read", "ai.use"})


def context(
    tenant: str = "tenant-a",
    user: str = "user-a",
    *,
    roles: frozenset[str] = frozenset({"organization_owner"}),
    permissions: frozenset[str] = ALL,
) -> AIContext:
    return AIContext(
        product_code="sample",
        environment="dev",
        tenant_id=tenant,
        organization_id=f"org-{tenant}",
        user_id=user,
        roles=roles,
        permissions=permissions,
    )


def runtime_for(
    provider: FakeProvider,
    *,
    catalogue: ModelCatalogue,
    tools: ToolRegistry,
    agents: AgentRegistry,
    limits: Limits | None = None,
    fail_closed: bool = False,
    store: InMemoryStore | None = None,
) -> tuple[AIRuntime, InMemoryStore, MemoryAuditSink]:
    providers = ProviderRegistry()
    providers.register("openai", provider)
    providers.register("anthropic", provider)
    memory = store or InMemoryStore()
    audit = MemoryAuditSink()
    runtime = AIRuntime(
        configuration=AIConfiguration(
            catalogue=catalogue,
            routing=StaticRouting(),
            fail_closed=fail_closed,
            limits=limits or Limits(),
        ),
        providers=providers,
        tools=tools,
        agents=agents,
        prompts=PromptRegistry(),
        store=memory,
        usage=memory,
        audit=audit,
    )
    return runtime, memory, audit
