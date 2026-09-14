"""The assistant surface: conversations, messages and the actions a person decides.

Seven routes, all under the customer's token, all scoped to the caller's tenant
by the dependency that assembles the runtime. There is no tenant, organization
or user in any path or body: `core/ai.py` builds the context from the verified
token and the resolved tenant, and a request body that names one is refused
as unknown input.

Refusals carry a code as well as a status. The web tier turns the code into a
sentence in the reader's language; the status is for everything else. Which
code answers which status is decided in `core/ai.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from koras_ai import (
    OPEN,
    AIError,
    Conversation,
    ErrorCode,
    PageContext,
    ProposedAction,
    StoredMessage,
    Turn,
    Usage,
)
from pydantic import BaseModel, ConfigDict, Field

from ..core import notify
from ..core.ai import AiDep, TenantAI, refusal
from ..core.settings import PRODUCT_CODE, settings

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


# ── what the API answers ─────────────────────────────────────────────────────


class UsageView(BaseModel):
    input: int
    output: int
    total: int


class ConversationView(BaseModel):
    id: str
    title: str
    agent_id: str
    context_type: str | None
    context_id: str | None
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    id: str
    role: str
    content: str
    tool_name: str | None
    created_at: datetime


class ActionView(BaseModel):
    id: str
    conversation_id: str
    tool_id: str
    operation: str
    status: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    proposed_by: str
    decided_by: str | None
    created_at: datetime
    decided_at: datetime | None


class ConversationDetail(BaseModel):
    conversation: ConversationView
    messages: list[MessageView]
    #: The actions still waiting for a person, oldest first.
    pending: list[ActionView]


class TurnView(BaseModel):
    conversation: ConversationView
    messages: list[MessageView]
    pending: list[ActionView]
    usage: UsageView


class ConversationList(BaseModel):
    conversations: list[ConversationView]


class StatusView(BaseModel):
    """Whether the assistant may be used, and how much of the allowance is left.

    `resolved` is false when the product has no platform and runs on its own
    catalogue, so the page can say so rather than show a quota of nothing.
    """

    enabled: bool
    tools_enabled: bool
    requests_this_month: int
    monthly_limit: int | None
    resolved: bool
    agents: list[str]


# ── what the API accepts ──────────────────────────────────────────────────────


class StartConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=120)
    #: The screen the assistant was opened beside. Informational; scopes nothing.
    context_type: str | None = Field(default=None, max_length=64)
    context_id: str | None = Field(default=None, max_length=128)


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=8000)


# ── views ────────────────────────────────────────────────────────────────────


def _conversation(conversation: Conversation) -> ConversationView:
    return ConversationView(
        id=conversation.id,
        title=conversation.title,
        agent_id=conversation.agent_id,
        context_type=conversation.page.type if conversation.page else None,
        context_id=conversation.page.id if conversation.page else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message(stored: StoredMessage) -> MessageView:
    return MessageView(
        id=stored.id,
        role=stored.message.role,
        content=stored.message.content,
        tool_name=stored.message.name,
        created_at=stored.created_at,
    )


def _action(action: ProposedAction) -> ActionView:
    return ActionView(
        id=action.id,
        conversation_id=action.conversation_id,
        tool_id=action.tool_id,
        operation=action.operation.value,
        status=action.status.value,
        input=dict(action.input),
        result=dict(action.result) if action.result is not None else None,
        error=action.error,
        proposed_by=action.proposed_by,
        decided_by=action.decided_by,
        created_at=action.created_at,
        decided_at=action.decided_at,
    )


def _usage(usage: Usage) -> UsageView:
    return UsageView(input=usage.input, output=usage.output, total=usage.total)


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/ai/status", response_model=StatusView)
async def ai_status(ai: AiDep) -> StatusView:
    try:
        state = await ai.runtime.status(ai.context)
    except AIError as error:
        raise refusal(error) from error
    return StatusView(
        enabled=ai.grant.enabled,
        tools_enabled=state.tools_enabled,
        requests_this_month=state.requests_this_month,
        monthly_limit=state.monthly_limit,
        resolved=ai.grant.resolved,
        agents=list(state.agents),
    )


@router.get("/ai/conversations", response_model=ConversationList)
async def list_conversations(ai: AiDep) -> ConversationList:
    conversations = await ai.runtime.store.list_conversations(ai.context)
    return ConversationList(conversations=[_conversation(c) for c in conversations])


@router.post(
    "/ai/conversations", response_model=ConversationView, status_code=status.HTTP_201_CREATED
)
async def start_conversation(body: StartConversation, ai: AiDep) -> ConversationView:
    page = (
        PageContext(type=body.context_type, id=body.context_id)
        if body.context_type and body.context_id
        else None
    )
    try:
        conversation = await ai.runtime.start(
            ai.context, agent_id=body.agent_id, title=body.title, page=page
        )
    except AIError as error:
        raise refusal(error) from error
    return _conversation(conversation)


@router.get("/ai/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, ai: AiDep) -> ConversationDetail:
    conversation = await ai.runtime.store.get_conversation(ai.context, conversation_id)
    if conversation is None:
        raise refusal(AIError(ErrorCode.NOT_FOUND, "no such conversation"))
    messages = await ai.runtime.store.list_messages(ai.context, conversation.id)
    pending = await ai.runtime.store.list_actions(ai.context, conversation.id, OPEN)
    return ConversationDetail(
        conversation=_conversation(conversation),
        messages=[_message(m) for m in messages],
        pending=[_action(a) for a in pending],
    )


async def _flush(ai: TenantAI) -> None:
    """Write the request's audit events. After the answer and after a refusal alike."""
    if ai.audit is not None:
        await ai.audit.flush()


async def _tell_approvers(ai: TenantAI, background: BackgroundTasks, turn: Turn) -> None:
    """Queue the approval notice for the actions this turn left waiting.

    Recipients are resolved here, on the request's session, and the mail is
    sent after the response. A failure to find or tell anybody is logged and
    never fails the turn: the action still waits in the assistant, which is
    where it waited before there was a notice at all.
    """
    waiting = notify.awaiting(turn.actions)
    if not waiting:
        return
    try:
        recipients = await notify.approvers(
            ai.session,
            tenant_id=ai.context.tenant_id,
            organization_id=ai.context.organization_id,
            token=ai.token,
        )
    except Exception:
        _log.exception("approvers could not be resolved; the action waits unannounced")
        return
    background.add_task(
        notify.notify_awaiting_approval,
        recipients=recipients,
        actions=list(waiting),
        product=PRODUCT_CODE,
        app_url=settings.next_public_app_url,
    )


@router.post("/ai/conversations/{conversation_id}/messages", response_model=TurnView)
async def send_message(
    conversation_id: str, body: SendMessage, ai: AiDep, background: BackgroundTasks
) -> TurnView:
    """One turn of the agent. Ends at an answer, or at an action waiting for a person."""
    try:
        turn = await ai.runtime.send(ai.context, conversation_id, body.text)
    except AIError as error:
        await _flush(ai)
        raise refusal(error) from error
    await _flush(ai)
    await _tell_approvers(ai, background, turn)
    return TurnView(
        conversation=_conversation(turn.conversation),
        messages=[_message(m) for m in turn.messages],
        pending=[_action(a) for a in turn.actions],
        usage=_usage(turn.usage),
    )


@router.post("/ai/actions/{action_id}/approve", response_model=ActionView)
async def approve_action(action_id: str, ai: AiDep) -> ActionView:
    """A person agrees. The runtime checks they may, then runs the tool."""
    try:
        return _action(await ai.runtime.approve(ai.context, action_id))
    except AIError as error:
        raise refusal(error) from error
    finally:
        await _flush(ai)


@router.post("/ai/actions/{action_id}/reject", response_model=ActionView)
async def reject_action(action_id: str, ai: AiDep) -> ActionView:
    try:
        return _action(await ai.runtime.reject(ai.context, action_id))
    except AIError as error:
        raise refusal(error) from error
    finally:
        await _flush(ai)


class AuditEventView(BaseModel):
    id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    outcome: str
    details: dict[str, Any]
    at: datetime


class AuditList(BaseModel):
    events: list[AuditEventView]


@router.get("/ai/audit", response_model=AuditList)
async def recent_audit(ai: AiDep, limit: int = 50) -> AuditList:
    """What the assistant proposed, ran, was refused and was decided, newest first.

    For the people who decide: the same permission that approves. Nothing
    here is content -- actor, action, target, outcome and the event's own
    detail map, which refuses anything named like a secret at construction.
    """
    if "ai.approve" not in ai.context.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "tool_denied",
                "message": "reading the assistant's activity needs ai.approve",
            },
        )
    if ai.audit is None:
        return AuditList(events=[])
    return AuditList(events=[AuditEventView(**row) for row in await ai.audit.recent(limit)])
