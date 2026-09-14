"""The assistant, assembled for one request: who, which plan, which routes, which rows.

Everything the runtime needs that the request already carries or the platform
already answers, put together once per request the way `core/storage.py`
assembles a tenant's bucket. Three reads and one construction:

    the tenant and the caller       TenantDep and AuthDep, verified
    the plan                        the portal's entitlements, cached a minute
    the routing                     the portal's AI routing per alias, lazily
    the rows                        the tenant-scoped session, through SqlStore

**The plan gates before anything runs.** The `ai.assistant` entitlement is
whether this organization may use the assistant at all; `ai.tools` is whether
its proposals may become actions; `ai.requests` is the monthly allowance, read
from the entitlement's limit. Refused with 402 like storage, because a missing
plan feature is a commercial fact and not a permission.

**A silent platform is a refusal here, unlike storage.** Storage falls back to
the product's bucket when the platform does not answer, because a customer
who paid for storage and cannot reach it is the worse outcome. A model call
costs money per request and sends the customer's text to a provider the
platform chose; running it on a guess is the worse outcome here. A product
with no platform configured at all is the documented bootstrap order and runs
on its own catalogue, ungated.

The provider is built once per process from the gateway settings and reused:
one connection pool, one credential read, and a product with AI enabled and
no gateway configured fails at the first request with a sentence naming the
setting rather than at the first model call with a connection error.
"""

from __future__ import annotations

import base64
import functools
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_ai import (
    ActionStatus,
    AIConfiguration,
    AIContext,
    AIError,
    AIRuntime,
    AliasPolicy,
    Citation,
    Conversation,
    ErrorCode,
    GatewayProvider,
    GenerateRequest,
    Limits,
    Message,
    ModelAlias,
    Operation,
    PageContext,
    Price,
    ProposedAction,
    ProviderEmbedder,
    ProviderRegistry,
    RetrievalScope,
    StoredMessage,
    ToolCall,
    Usage,
    UsageEvent,
    estimated_cost_micros,
)
from koras_audit import AuditEvent
from koras_auth import JWTClaims
from koras_auth.permissions import permissions_for
from koras_storage import ObjectStore
from koras_tenant import TenantContext
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import registries
from ..ai.prompts import OCR_INSTRUCTIONS
from . import knowledge as knowledge_store
from . import platform
from .auth import AuthDep
from .database import DbSession, rebind_tenant, tenant_session
from .settings import PRODUCT_CODE, settings
from .storage import tenant_storage
from .tenant import TenantDep

#: The platform entitlements that gate the assistant. Named once here and once
#: in `packages/branding`'s navigation registry; the generator's structural test
#: asserts the two agree.
AI_ENTITLEMENT = "ai.assistant"
AI_TOOLS_ENTITLEMENT = "ai.tools"
AI_REQUESTS_ENTITLEMENT = "ai.requests"
#: Pay as you go beyond the allowance: `enabled` is the customer's consent,
#: `limit_value` the month's charge limit in US cents, and the row's
#: `config.rate_percent` the staff multiplier (400 is four times cost).
AI_OVERAGE_ENTITLEMENT = "ai.overage"
DEFAULT_OVERAGE_RATE_PERCENT = 400

_bearer = HTTPBearer(auto_error=True)

_log = logging.getLogger(__name__)

#: How an AI refusal is answered. One status per code, decided here and read
#: by the router; the web tier turns the code into a sentence.
STATUS_FOR: dict[ErrorCode, int] = {
    ErrorCode.AI_DISABLED: status.HTTP_404_NOT_FOUND,
    ErrorCode.ENTITLEMENT_MISSING: status.HTTP_402_PAYMENT_REQUIRED,
    ErrorCode.USAGE_EXCEEDED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.PROVIDER_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.INVALID_MODEL_ALIAS: status.HTTP_400_BAD_REQUEST,
    ErrorCode.TOOL_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.APPROVAL_REQUIRED: status.HTTP_409_CONFLICT,
    ErrorCode.UNREGISTERED_ACTION: status.HTTP_400_BAD_REQUEST,
    ErrorCode.RETRIEVAL_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCode.UPSTREAM_ERROR: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.CONFIGURATION_ERROR: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.INVALID_INPUT: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.INVALID_STATE: status.HTTP_409_CONFLICT,
}


def refusal(error: AIError) -> HTTPException:
    """An AI error as the API answers it: the code and the safe sentence, never the detail.

    The detail goes to the log instead, and only for a failure on this side
    of the customer -- a 5xx. The page tells them "the reason is in the server
    log", and for the first conversation on dev the log held only a status
    line: an alias nobody had routed, and nothing said which one. A refusal
    the customer caused (a missing entitlement, a quota, a bad alias) is
    theirs to read on the page and is not an operator's problem.
    """
    code = STATUS_FOR.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR)
    if code >= 500:
        _log.warning(
            "AI refused with %s (%s): %s -- %s",
            code,
            error.code.value,
            error.message,
            error.detail or "no further detail",
        )
    return HTTPException(
        status_code=code,
        detail={"code": error.code.value, "message": error.message},
    )


# ── the plan ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AiGrant:
    """What the plan says about the assistant for this organization."""

    enabled: bool
    tools: bool
    monthly_requests: int | None
    #: False when no platform is configured, so the product runs on its own.
    resolved: bool
    overage_enabled: bool = False
    overage_rate_percent: int = DEFAULT_OVERAGE_RATE_PERCENT
    overage_cap_micros: int | None = None


def grant_from(answer: platform.PortalAnswer | None, *, configured: bool) -> AiGrant:
    if answer is None:
        if configured:
            # A platform exists and did not answer. See the module docstring.
            raise AIError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "the platform could not be reached to confirm this plan",
                detail="entitlements unanswered with a Control Plane configured",
            )
        return AiGrant(enabled=True, tools=True, monthly_requests=None, resolved=False)
    body = answer.body
    if body is None:
        return AiGrant(enabled=False, tools=False, monthly_requests=None, resolved=True)
    rows: dict[str, dict[str, Any]] = {}
    for row in body.get("entitlements", []) or []:
        if isinstance(row, dict) and isinstance(row.get("code"), str):
            rows[row["code"]] = row
    assistant = rows.get(AI_ENTITLEMENT, {})
    tools = rows.get(AI_TOOLS_ENTITLEMENT, {})
    requests = rows.get(AI_REQUESTS_ENTITLEMENT, {})
    limit = requests.get("limit_value")
    overage = rows.get(AI_OVERAGE_ENTITLEMENT, {})
    cap_cents = overage.get("limit_value")
    raw_config = overage.get("config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    rate = config.get("rate_percent")
    return AiGrant(
        enabled=bool(assistant.get("enabled")),
        tools=bool(tools.get("enabled")),
        monthly_requests=int(limit)
        if bool(requests.get("enabled")) and isinstance(limit, int) and limit >= 0
        else None,
        resolved=True,
        overage_enabled=bool(overage.get("enabled")),
        overage_rate_percent=int(rate)
        if isinstance(rate, int) and rate > 0
        else DEFAULT_OVERAGE_RATE_PERCENT,
        overage_cap_micros=int(cap_cents) * 10_000
        if isinstance(cap_cents, int) and cap_cents > 0
        else None,
    )


# ── the routing ───────────────────────────────────────────────────────────────


class ControlPlaneRouting:
    """The platform's routing policy per alias, read with the caller's token."""

    def __init__(self, *, organization_id: str, token: str) -> None:
        self._organization_id = organization_id
        self._token = token

    async def policy_for(self, alias: str) -> AliasPolicy | None:
        routing = await platform.ai_routing(
            alias, organization_id=self._organization_id, token=self._token
        )
        if routing is None:
            return None
        return AliasPolicy(
            providers=tuple(routing.providers),
            model=_name(routing.config.get("model")),
            fallback_model=_name(routing.config.get("fallback_model")),
            prices=_prices(routing.config.get("prices")),
        )


def _name(value: object) -> str | None:
    """A model name out of the policy's configuration, or nothing."""
    return value if isinstance(value, str) and value else None


def _prices(value: object) -> dict[str, Price]:
    """The list price per model the policy carried, or nothing.

    A malformed entry is dropped rather than guessed: a price that cannot be
    read is a usage row with no estimate, which the platform can see and
    correct, where a price read wrongly is a wrong number nobody questions.
    """
    if not isinstance(value, dict):
        return {}
    prices: dict[str, Price] = {}
    for model, entry in value.items():
        if not (isinstance(model, str) and model and isinstance(entry, dict)):
            continue
        cents_in = entry.get("input_cents_per_million")
        cents_out = entry.get("output_cents_per_million")
        if (
            isinstance(cents_in, int)
            and isinstance(cents_out, int)
            and not isinstance(cents_in, bool)
            and not isinstance(cents_out, bool)
            and cents_in >= 0
            and cents_out >= 0
        ):
            prices[model] = Price(cents_in, cents_out)
    return prices


# ── the rows ──────────────────────────────────────────────────────────────────


def _dt(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _json(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


class SqlStore:
    """The conversation store and the usage recorder, in SQL, on the tenant session.

    Every statement names the tenant as well as running under the policies
    that would scope it anyway -- belt and braces, for the reason the tenant
    router gives: a policy is a backstop against a query that forgets, not a
    substitute for one that remembers.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def _commit(self) -> None:
        """Commit, then bind the tenant again.

        The tenant context the policies filter on is transaction-local by
        design, so it cannot outlive a request on a pooled connection. A
        commit ends that transaction, and the next statement on this session
        would run with no tenant -- every policy matches nothing, and an
        insert is refused. The first real conversation on dev recorded its
        usage that way: the message committed, the usage row violated the
        policy. Rebinding after each commit is what keeps "one request, one
        tenant" true across the several transactions a turn takes.
        """
        await self._session.commit()
        await rebind_tenant(self._session, self._tenant_id)

    async def create_conversation(
        self, context: AIContext, *, agent_id: str, title: str, page: PageContext | None
    ) -> Conversation:
        row = (
            await self._session.execute(
                text(
                    "insert into public.ai_conversations "
                    "(tenant_id, created_by, agent_id, title, context_type, context_id) "
                    "values (:tenant_id, :created_by, :agent_id, :title, "
                    " :context_type, :context_id) "
                    "returning id::text, created_at, updated_at"
                ),
                {
                    "tenant_id": context.tenant_id,
                    "created_by": context.user_id,
                    "agent_id": agent_id,
                    "title": title,
                    "context_type": page.type if page else None,
                    "context_id": page.id if page else None,
                },
            )
        ).one()
        await self._commit()
        return Conversation(
            id=row.id,
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            agent_id=agent_id,
            title=title,
            created_at=_dt(row.created_at),
            updated_at=_dt(row.updated_at),
            page=page,
        )

    async def list_conversations(self, context: AIContext) -> list[Conversation]:
        rows = await self._session.execute(
            text(
                "select id::text, created_by, agent_id, title, context_type, context_id, "
                "created_at, updated_at from public.ai_conversations "
                "where tenant_id = :tenant_id order by updated_at desc limit 50"
            ),
            {"tenant_id": context.tenant_id},
        )
        return [self._conversation(context, row) for row in rows.fetchall()]

    async def get_conversation(
        self, context: AIContext, conversation_id: str
    ) -> Conversation | None:
        rows = await self._session.execute(
            text(
                "select id::text, created_by, agent_id, title, context_type, context_id, "
                "created_at, updated_at from public.ai_conversations "
                "where tenant_id = :tenant_id and id::text = :id"
            ),
            {"tenant_id": context.tenant_id, "id": conversation_id},
        )
        row = rows.first()
        return self._conversation(context, row) if row is not None else None

    def _conversation(self, context: AIContext, row: Row[Any]) -> Conversation:
        page = (
            PageContext(type=row.context_type, id=row.context_id)
            if row.context_type and row.context_id
            else None
        )
        return Conversation(
            id=row.id,
            tenant_id=context.tenant_id,
            created_by=row.created_by,
            agent_id=row.agent_id,
            title=row.title,
            created_at=_dt(row.created_at),
            updated_at=_dt(row.updated_at),
            page=page,
        )

    async def list_messages(self, context: AIContext, conversation_id: str) -> list[StoredMessage]:
        rows = await self._session.execute(
            text(
                "select id::text, conversation_id::text, role, content, tool_calls, "
                "tool_call_id, tool_name, created_at from public.ai_messages "
                "where tenant_id = :tenant_id and conversation_id::text = :conversation_id "
                "order by created_at, id"
            ),
            {"tenant_id": context.tenant_id, "conversation_id": conversation_id},
        )
        out: list[StoredMessage] = []
        for row in rows.fetchall():
            calls = _json(row.tool_calls).get("calls", [])
            out.append(
                StoredMessage(
                    id=row.id,
                    tenant_id=context.tenant_id,
                    conversation_id=row.conversation_id,
                    message=Message(
                        role=row.role,
                        content=row.content or "",
                        tool_calls=tuple(
                            ToolCall(
                                id=str(call.get("id", "")),
                                name=str(call.get("name", "")),
                                arguments=dict(call.get("arguments", {})),
                            )
                            for call in calls
                            if isinstance(call, dict)
                        ),
                        tool_call_id=row.tool_call_id,
                        name=row.tool_name,
                    ),
                    created_at=_dt(row.created_at),
                )
            )
        return out

    async def add_message(
        self, context: AIContext, conversation_id: str, message: Message
    ) -> StoredMessage:
        calls = {
            "calls": [
                {"id": c.id, "name": c.name, "arguments": dict(c.arguments)}
                for c in message.tool_calls
            ]
        }
        row = (
            await self._session.execute(
                text(
                    "insert into public.ai_messages "
                    "(tenant_id, conversation_id, role, content, tool_calls, "
                    " tool_call_id, tool_name) "
                    "select :tenant_id, c.id, :role, :content, cast(:tool_calls as jsonb), "
                    "  :tool_call_id, :tool_name "
                    "from public.ai_conversations c "
                    "where c.tenant_id = :tenant_id and c.id::text = :conversation_id "
                    "returning id::text, conversation_id::text, created_at"
                ),
                {
                    "tenant_id": context.tenant_id,
                    "conversation_id": conversation_id,
                    "role": message.role,
                    "content": message.content,
                    "tool_calls": json.dumps(calls),
                    "tool_call_id": message.tool_call_id,
                    "tool_name": message.name,
                },
            )
        ).first()
        if row is None:
            raise KeyError(conversation_id)
        await self._session.execute(
            text(
                "update public.ai_conversations set updated_at = now() "
                "where tenant_id = :tenant_id and id::text = :conversation_id"
            ),
            {"tenant_id": context.tenant_id, "conversation_id": conversation_id},
        )
        await self._commit()
        return StoredMessage(
            id=row.id,
            tenant_id=context.tenant_id,
            conversation_id=row.conversation_id,
            message=message,
            created_at=_dt(row.created_at),
        )

    async def create_action(self, context: AIContext, action: ProposedAction) -> ProposedAction:
        if action.tenant_id != context.tenant_id:
            raise KeyError(action.id)
        await self._session.execute(
            text(
                "insert into public.ai_actions "
                "(id, tenant_id, conversation_id, message_id, tool_id, tool_call_id, operation, "
                " input, status, proposed_by, decided_by, decided_at, result, error, executed_at) "
                "values (cast(:id as uuid), :tenant_id, cast(:conversation_id as uuid), "
                " cast(:message_id as uuid), :tool_id, :tool_call_id, :operation, "
                " cast(:input as jsonb), :status, :proposed_by, :decided_by, :decided_at, "
                " cast(:result as jsonb), :error, :executed_at)"
            ),
            self._action_params(action),
        )
        await self._commit()
        return action

    async def get_action(self, context: AIContext, action_id: str) -> ProposedAction | None:
        rows = await self._session.execute(
            text(
                "select id::text, conversation_id::text, message_id::text, tool_id, tool_call_id, "
                "operation, input, status, proposed_by, decided_by, decided_at, result, error, "
                "executed_at, created_at from public.ai_actions "
                "where tenant_id = :tenant_id and id::text = :id"
            ),
            {"tenant_id": context.tenant_id, "id": action_id},
        )
        row = rows.first()
        return self._action(context, row) if row is not None else None

    async def list_actions(
        self,
        context: AIContext,
        conversation_id: str,
        statuses: Iterable[ActionStatus] | None = None,
    ) -> list[ProposedAction]:
        wanted = [s.value for s in statuses] if statuses is not None else None
        rows = await self._session.execute(
            text(
                "select id::text, conversation_id::text, message_id::text, tool_id, tool_call_id, "
                "operation, input, status, proposed_by, decided_by, decided_at, result, error, "
                "executed_at, created_at from public.ai_actions "
                "where tenant_id = :tenant_id and conversation_id::text = :conversation_id "
                "and (cast(:any_status as boolean) or status = any(cast(:statuses as text[]))) "
                "order by created_at"
            ),
            {
                "tenant_id": context.tenant_id,
                "conversation_id": conversation_id,
                "any_status": wanted is None,
                "statuses": wanted or [],
            },
        )
        return [self._action(context, row) for row in rows.fetchall()]

    async def update_action(self, context: AIContext, action: ProposedAction) -> ProposedAction:
        result = await self._session.execute(
            text(
                "update public.ai_actions set status = :status, decided_by = :decided_by, "
                "decided_at = :decided_at, result = cast(:result as jsonb), error = :error, "
                "executed_at = :executed_at "
                "where tenant_id = :tenant_id and id::text = :id "
                "returning id::text"
            ),
            self._action_params(action),
        )
        if result.first() is None:
            raise KeyError(action.id)
        await self._commit()
        return action

    def _action_params(self, action: ProposedAction) -> dict[str, Any]:
        return {
            "id": action.id,
            "tenant_id": action.tenant_id,
            "conversation_id": action.conversation_id,
            "message_id": action.message_id,
            "tool_id": action.tool_id,
            "tool_call_id": action.tool_call_id,
            "operation": action.operation.value,
            "input": json.dumps(dict(action.input), default=str),
            "status": action.status.value,
            "proposed_by": action.proposed_by,
            "decided_by": action.decided_by,
            "decided_at": action.decided_at,
            "result": json.dumps(dict(action.result), default=str) if action.result else None,
            "error": action.error,
            "executed_at": action.executed_at,
        }

    def _action(self, context: AIContext, row: Row[Any]) -> ProposedAction:
        return ProposedAction(
            id=row.id,
            tenant_id=context.tenant_id,
            conversation_id=row.conversation_id,
            message_id=row.message_id,
            tool_id=row.tool_id,
            tool_call_id=row.tool_call_id,
            operation=Operation(row.operation),
            input=_json(row.input),
            status=ActionStatus(row.status),
            proposed_by=row.proposed_by,
            created_at=_dt(row.created_at),
            decided_by=row.decided_by,
            decided_at=_dt(row.decided_at) if row.decided_at else None,
            executed_at=_dt(row.executed_at) if row.executed_at else None,
            result=_json(row.result) if row.result else None,
            error=row.error,
        )

    async def record(self, event: UsageEvent) -> None:
        await self._session.execute(
            text(
                "insert into public.ai_usage_events "
                "(tenant_id, user_id, conversation_id, agent_id, model_alias, provider, model, "
                " input_tokens, output_tokens, total_tokens, latency_ms, status, error_code, "
                " estimated_cost_micros, over_allowance, billable_micros, overage_rate_percent) "
                "values (:tenant_id, :user_id, cast(:conversation_id as uuid), :agent_id, "
                " :model_alias, :provider, :model, :input_tokens, :output_tokens, :total_tokens, "
                " :latency_ms, :status, :error_code, :estimated_cost_micros, :over_allowance, "
                " :billable_micros, :overage_rate_percent)"
            ),
            {
                "estimated_cost_micros": event.estimated_cost_micros,
                "over_allowance": event.over_allowance,
                "billable_micros": event.billable_micros,
                "overage_rate_percent": event.overage_rate_percent,
                "tenant_id": event.tenant_id,
                "user_id": event.user_id,
                "conversation_id": event.conversation_id,
                "agent_id": event.agent_id,
                "model_alias": event.model_alias,
                "provider": event.provider,
                "model": event.model,
                "input_tokens": event.usage.input,
                "output_tokens": event.usage.output,
                "total_tokens": event.usage.total,
                "latency_ms": event.latency_ms,
                "status": event.status,
                "error_code": event.error_code,
            },
        )
        await self._commit()

    async def requests_since(self, tenant_id: str, since: datetime) -> int:
        result = await self._session.execute(
            text(
                "select count(*) from public.ai_usage_events "
                "where tenant_id = :tenant_id and created_at >= :since and status = 'ok'"
            ),
            {"tenant_id": tenant_id, "since": since},
        )
        return int(result.scalar_one())

    async def billable_since(self, tenant_id: str, since: datetime) -> int:
        result = await self._session.execute(
            text(
                "select coalesce(sum(billable_micros), 0) from public.ai_usage_events "
                "where tenant_id = :tenant_id and created_at >= :since"
            ),
            {"tenant_id": tenant_id, "since": since},
        )
        return int(result.scalar_one())


# ── the dependency ────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def gateway() -> GatewayProvider:
    """The one gateway client for this process, built on first use.

    Cached the way the JWKS cache is held: once per process. An unconfigured
    gateway raises rather than caching, so the first request after the
    setting is fixed builds a working client.
    """
    return GatewayProvider(
        base_url=settings.ai_gateway_url,
        api_key=settings.litellm_master_key,
    )


@dataclass(frozen=True)
class TenantAI:
    runtime: AIRuntime
    context: AIContext
    grant: AiGrant
    #: The caller's own token, for the platform reads a turn may need after
    #: the runtime has answered -- who may approve, for one.
    token: str = ""
    #: The durable audit for this request, flushed by the route once the
    #: runtime is done. None in tests that run without a database.
    audit: SqlAuditSink | None = None
    session: AsyncSession | None = None
    #: Who is asking, as the token said, for a notice that names a person
    #: rather than a subject id.
    requester_name: str | None = None
    requester_email: str | None = None


async def tenant_ai(
    tenant: TenantDep,
    claims: AuthDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    session: DbSession,
) -> TenantAI:
    """Everything one AI request needs, or a refusal saying which part is missing."""
    return await assemble_tenant_ai(tenant, claims, credentials, session)


@dataclass(frozen=True)
class AiAssembly:
    """`tenant_ai` with the session left open, for a route that answers over time.

    A streamed answer outlives the request's own session, which the
    framework closes on its own schedule, so the route opens one of its
    own and builds the runtime on it. The tenant is here so the route can
    declare it for that session before anything is read.
    """

    tenant_id: str
    build: Callable[[AsyncSession], Awaitable[TenantAI]]


async def tenant_ai_factory(
    tenant: TenantDep,
    claims: AuthDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> AiAssembly:
    async def build(session: AsyncSession) -> TenantAI:
        return await assemble_tenant_ai(tenant, claims, credentials, session)

    return AiAssembly(tenant_id=tenant.id, build=build)


async def assemble_tenant_ai(
    tenant: TenantContext,
    claims: JWTClaims,
    credentials: HTTPAuthorizationCredentials,
    session: AsyncSession,
) -> TenantAI:
    token = credentials.credentials
    configured = platform.configured()
    try:
        answer = await platform.read_portal(
            f"/api/portal/v1/products/{PRODUCT_CODE}/entitlements",
            organization_id=tenant.organization_id,
            token=token,
        )
        grant = grant_from(answer, configured=configured)
    except AIError as error:
        raise refusal(error) from error

    if not grant.enabled:
        raise refusal(
            AIError(
                ErrorCode.ENTITLEMENT_MISSING,
                f"this organization's plan does not include {AI_ENTITLEMENT}",
            )
        )

    context = AIContext(
        product_code=PRODUCT_CODE,
        environment=settings.environment.value,
        tenant_id=tenant.id,
        organization_id=tenant.organization_id,
        user_id=claims.sub,
        roles=frozenset(role.value for role in claims.roles),
        permissions=permissions_for(claims.roles),
    )

    try:
        provider = gateway()
    except AIError as error:
        raise refusal(error) from error
    providers = ProviderRegistry()
    for name in registries.PROVIDER_NAMES:
        providers.register(name, provider)

    store = SqlStore(session, tenant.id)
    configuration = AIConfiguration(
        catalogue=registries.catalogue,
        routing=ControlPlaneRouting(organization_id=tenant.organization_id, token=token),
        fail_closed=configured,
        limits=Limits(
            monthly_requests=grant.monthly_requests,
            tools_enabled=grant.tools,
            overage_enabled=grant.overage_enabled,
            overage_rate_percent=grant.overage_rate_percent,
            overage_cap_micros=grant.overage_cap_micros,
        ),
    )
    embed = embedder(configuration, providers)
    scope = RetrievalScope(tenant_id=tenant.id, product_code=PRODUCT_CODE)

    async def retrieve(query: str, limit: int) -> list[Citation]:
        try:
            return await knowledge_store.search(
                session, scope=scope, query=query, embed=embed, limit=limit
            )
        except AIError:
            raise
        except Exception as error:
            # A failed statement leaves the session in an aborted transaction,
            # and the runtime still has the action's outcome to record on it.
            # Roll back, bind the tenant again, and hand the runtime a named
            # failure it turns into a tool result rather than a 500.
            await session.rollback()
            await rebind_tenant(session, tenant.id)
            _log.warning("retrieval failed: %s", type(error).__name__)
            raise AIError(
                ErrorCode.RETRIEVAL_FAILED, "the organization's documents could not be searched"
            ) from error

    async def object_store() -> ObjectStore:
        # Resolved only when a tool asks for it: the storage policy is one
        # more platform read, and most turns never touch a file.
        return (await tenant_storage(tenant, credentials)).store

    sink = SqlAuditSink(session, tenant.id)
    runtime = AIRuntime(
        configuration=configuration,
        providers=providers,
        tools=registries.tools,
        agents=registries.agents,
        prompts=registries.prompts,
        store=store,
        usage=store,
        audit=sink,
        session=session,
        # The object store, so a tool that deletes a file never builds a
        # credentialed client of its own; resolved for this tenant the way the
        # Files page resolves it.
        services={"embed": embed, "retrieve": retrieve, "storage": object_store},
    )
    return TenantAI(
        runtime=runtime,
        context=context,
        grant=grant,
        token=token,
        audit=sink,
        session=session,
        requester_name=claims.name,
        requester_email=claims.email,
    )


def embedder(configuration: AIConfiguration, providers: ProviderRegistry) -> knowledge_store.Embed:
    """Embeds under the embedding alias, through whichever provider the
    routing names first and the registry holds."""

    async def embed(texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        for route in await configuration.routes_for(ModelAlias.EMBEDDING):
            provider_for = providers.get(route.provider)
            if provider_for is None:
                continue
            return await ProviderEmbedder(provider_for, route).embed(texts)
        raise AIError(
            ErrorCode.CONFIGURATION_ERROR,
            "no provider is registered for the routes the embedding alias resolves to",
        )

    return embed


#: The agent id a page read for indexing is metered under. Not a
#: conversation: the usage row has none, and the audit names the file.
OCR_AGENT = "knowledge.ocr"
#: The vision call is bounded: one page, one transcription.
OCR_MAX_OUTPUT = 4000
_TRY_NEXT_ROUTE = frozenset(
    {ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.TIMEOUT, ErrorCode.UPSTREAM_ERROR}
)


def page_reader(
    configuration: AIConfiguration,
    providers: ProviderRegistry,
    *,
    tenant_id: str,
    user_id: str,
    record: Callable[[UsageEvent], Awaitable[None]],
) -> knowledge_store.ReadPages:
    """Reads pages through the vision alias, one call per page, each metered.

    Routes are tried in the order the routing names them, the way the
    runtime tries them for a turn, and every attempt is recorded before the
    next: a page that cost tokens and failed still cost them.
    """

    async def read_page(request: GenerateRequest) -> str:
        last: AIError | None = None
        for position, route in enumerate(
            routes := await configuration.routes_for(ModelAlias.VISION)
        ):
            provider = providers.get(route.provider)
            if provider is None:
                continue
            started = datetime.now(UTC)
            try:
                result = await provider.generate(request, route=route)
            except AIError as error:
                await record(
                    UsageEvent(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        agent_id=OCR_AGENT,
                        model_alias=ModelAlias.VISION.value,
                        provider=route.provider,
                        model=route.model,
                        usage=Usage(),
                        latency_ms=0,
                        status="error",
                        error_code=error.code.value,
                        created_at=started,
                    )
                )
                last = error
                if error.code in _TRY_NEXT_ROUTE and position < len(routes) - 1:
                    continue
                raise
            await record(
                UsageEvent(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=OCR_AGENT,
                    model_alias=ModelAlias.VISION.value,
                    provider=result.provider,
                    model=result.model,
                    usage=result.usage,
                    latency_ms=result.latency_ms,
                    status="ok",
                    created_at=datetime.now(UTC),
                    estimated_cost_micros=(
                        estimated_cost_micros(result.usage, route.price)
                        if route.price is not None
                        else None
                    ),
                )
            )
            return result.message.content
        if last is not None:
            raise last
        raise AIError(
            ErrorCode.CONFIGURATION_ERROR,
            "no provider is registered for the routes the vision alias resolves to",
        )

    async def read(pages: Sequence[knowledge_store.Page]) -> list[str]:
        texts: list[str] = []
        for image, kind in pages:
            data_url = f"data:{kind};base64,{base64.b64encode(image).decode('ascii')}"
            texts.append(
                await read_page(
                    GenerateRequest(
                        model=ModelAlias.VISION.value,
                        messages=(
                            Message("system", OCR_INSTRUCTIONS),
                            Message("user", "Transcribe this page.", images=(data_url,)),
                        ),
                        temperature=0.0,
                        max_output=OCR_MAX_OUTPUT,
                        metadata={"agent": OCR_AGENT},
                    )
                )
            )
        return texts

    return read


async def index_uploaded_file(
    *,
    tenant_id: str,
    organization_id: str,
    token: str,
    file_id: str,
    name: str,
    content_type: str,
    url: str,
    user_id: str = "",
) -> int:
    """Read a finished upload back from the bucket and index it for retrieval.

    Runs after the upload's response, on a session of its own scoped to the
    tenant. Anything that goes wrong is logged and leaves no chunks: a file
    that could not be indexed is a file the assistant answers about from its
    name, not an upload that failed.
    """
    try:
        return await _index_uploaded_file(
            tenant_id=tenant_id,
            organization_id=organization_id,
            token=token,
            file_id=file_id,
            name=name,
            content_type=content_type,
            url=url,
            user_id=user_id,
        )
    except Exception:
        _log.exception("file %s could not be indexed", file_id)
        await _record_index(tenant_id, file_id, indexed=False, note="indexing failed unexpectedly")
        return 0


_INDEX_STATE = text(
    "update public.files set indexed_at = :indexed_at, index_note = :note "
    "where id = cast(:id as uuid) and tenant_id = :tenant_id"
)


async def _record_index(tenant_id: str, file_id: str, *, indexed: bool, note: str) -> None:
    """Write the outcome on the file row, so it can be read rather than guessed."""
    try:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                _INDEX_STATE,
                {
                    "indexed_at": datetime.now(UTC) if indexed else None,
                    "note": note,
                    "id": file_id,
                    "tenant_id": tenant_id,
                },
            )
            await session.commit()
    except Exception:
        _log.exception("the indexing outcome for file %s could not be recorded", file_id)


async def _index_uploaded_file(
    *,
    tenant_id: str,
    organization_id: str,
    token: str,
    file_id: str,
    name: str,
    content_type: str,
    url: str,
    user_id: str = "",
) -> int:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            raw = response.content
    except httpx.HTTPError as error:
        _log.warning(
            "file %s could not be read back for indexing: %s", file_id, type(error).__name__
        )
        await _record_index(
            tenant_id, file_id, indexed=False, note="could not be read back from the bucket"
        )
        return 0
    providers = ProviderRegistry()
    try:
        provider = gateway()
    except AIError:
        _log.info("file %s is not indexed: no AI gateway configured", file_id)
        await _record_index(tenant_id, file_id, indexed=False, note="no AI gateway configured")
        return 0
    for provider_name in registries.PROVIDER_NAMES:
        providers.register(provider_name, provider)
    configuration = AIConfiguration(
        catalogue=registries.catalogue,
        routing=ControlPlaneRouting(organization_id=organization_id, token=token),
        fail_closed=platform.configured(),
        limits=Limits(),
    )
    try:
        async with tenant_session(tenant_id) as session:
            # Pages are read on this session so each vision call is metered
            # under the tenant, the way a turn's calls are.
            read = page_reader(
                configuration,
                providers,
                tenant_id=tenant_id,
                user_id=user_id,
                record=SqlStore(session, tenant_id).record,
            )
            extracted = await knowledge_store.text_for_index(
                raw, content_type=content_type, read=read
            )
            if extracted.text is None:
                _log.info("file %s is not indexed: nothing readable in it", file_id)
                await _record_index(
                    tenant_id,
                    file_id,
                    indexed=False,
                    note=(
                        "no text to index: not a text type, nothing readable on its "
                        "pages, or past the size ceiling"
                    ),
                )
                return 0
            document = knowledge_store.file_document(
                tenant_id=tenant_id, file_id=file_id, name=name, text_content=extracted.text
            )
            count = await knowledge_store.index_document(
                session,
                scope=RetrievalScope(tenant_id=tenant_id, product_code=PRODUCT_CODE),
                document=document,
                embed=embedder(configuration, providers),
            )
    except AIError as error:
        _log.warning("file %s is not indexed: %s", file_id, error)
        await _record_index(tenant_id, file_id, indexed=False, note=error.message)
        return 0
    how = (
        f"read with OCR: {extracted.pages} page(s), {count} chunk(s)"
        if extracted.method == "ocr"
        else f"{count} chunk(s)"
    )
    _log.info("file %s indexed: %s", file_id, how)
    await _record_index(tenant_id, file_id, indexed=True, note=how)
    return count


AiDep = Annotated[TenantAI, Depends(tenant_ai)]
AiFactoryDep = Annotated[AiAssembly, Depends(tenant_ai_factory)]


# ── the durable audit ─────────────────────────────────────────────────────────

_AUDIT_INSERT = text(
    "insert into public.ai_audit_events "
    "(tenant_id, actor_id, action, target_type, target_id, outcome, details, created_at) "
    "values (:tenant_id, :actor_id, :action, :target_type, :target_id, :outcome, "
    " cast(:details as jsonb), :created_at)"
)

_AUDIT_RECENT = text(
    "select id::text as id, actor_id, action, target_type, target_id, outcome, details, "
    " created_at "
    "from public.ai_audit_events where tenant_id = :tenant_id "
    "order by created_at desc limit :limit"
)


class SqlAuditSink:
    """`AuditSink` that keeps the request's events and writes them on the tenant session.

    The runtime emits synchronously and the database is asynchronous, so the
    events wait in a list until the route calls `flush`, once the runtime has
    answered or refused. A refusal is audited too, which is why the routes
    flush in a `finally`. Every event must name this tenant: the sink refuses
    one that does not, because the session it writes on could not store it
    anyway and a silent drop is the wrong way to learn that.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._pending: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        if event.tenant_id != self._tenant_id:
            raise ValueError("an audit event for another tenant cannot be recorded here")
        self._pending.append(event)

    async def flush(self) -> int:
        events, self._pending = self._pending, []
        for event in events:
            await self._session.execute(
                _AUDIT_INSERT,
                {
                    "tenant_id": event.tenant_id,
                    "actor_id": event.actor_id,
                    "action": event.action,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "outcome": str(event.outcome),
                    "details": json.dumps(dict(event.details)),
                    "created_at": event.at,
                },
            )
        if events:
            await self._session.commit()
            await rebind_tenant(self._session, self._tenant_id)
        return len(events)

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            _AUDIT_RECENT, {"tenant_id": self._tenant_id, "limit": max(1, min(limit, 200))}
        )
        return [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "outcome": row.outcome,
                "details": _json(row.details),
                "at": _dt(row.created_at),
            }
            for row in rows.fetchall()
        ]


# ── what the platform collects ────────────────────────────────────────────────

_USAGE_DAYS = text(
    "select tenant_id::text as tenant_id, "
    " (created_at at time zone 'UTC')::date as day, model_alias, provider, model, "
    " count(*)::int as calls, "
    " (count(*) filter (where status <> 'ok'))::int as errors, "
    " coalesce(sum(input_tokens), 0)::bigint as input_tokens, "
    " coalesce(sum(output_tokens), 0)::bigint as output_tokens, "
    " coalesce(sum(total_tokens), 0)::bigint as total_tokens, "
    " coalesce(sum(estimated_cost_micros), 0)::bigint as estimated_cost_micros, "
    " (count(*) filter (where over_allowance and status = 'ok'))::int as overage_calls, "
    " coalesce(sum(billable_micros), 0)::bigint as billable_micros "
    "from public.ai_usage_events "
    "where created_at >= cast(:since as date) "
    "group by 1, 2, 3, 4, 5 "
    "order by 2, 1, 3, 4, 5"
)


async def usage_days_since(session: AsyncSession, since: date) -> list[dict[str, Any]]:
    """Every tenant's usage per UTC day, alias, provider and model, from `since`.

    Read on the provisioning session, which the policy on `ai_usage_events`
    admits for select and nothing else -- so this is the one place the
    product hands usage across tenants, and it hands it to a machine identity
    only. Aggregates, never rows: the platform bills and shows totals, and a
    conversation id or a user id has no business leaving the product.
    """
    result = await session.execute(_USAGE_DAYS, {"since": since})
    return [dict(row) for row in result.mappings().all()]
