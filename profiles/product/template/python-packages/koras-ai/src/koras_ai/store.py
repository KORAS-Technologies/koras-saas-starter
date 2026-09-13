"""Where conversations, messages and actions are kept.

`ConversationStore` is a protocol so the runtime can be tested without a
database and so the API can implement it in SQL against the tenant-scoped
session it already opens. Every method takes the context, and every
implementation scopes on `context.tenant_id`: an id from another tenant is
not found, not forbidden, because saying "forbidden" confirms the id exists.

`InMemoryStore` is the test implementation and also implements the usage
recorder, so a runtime under test needs one object.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from .actions import ActionStatus, ProposedAction
from .context import AIContext, PageContext
from .tools import Operation
from .types import Message
from .usage import UsageEvent


@dataclass(frozen=True)
class Conversation:
    id: str
    tenant_id: str
    created_by: str
    agent_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    page: PageContext | None = None


@dataclass(frozen=True)
class StoredMessage:
    id: str
    tenant_id: str
    conversation_id: str
    message: Message
    created_at: datetime


class ConversationStore(Protocol):
    async def create_conversation(
        self, context: AIContext, *, agent_id: str, title: str, page: PageContext | None
    ) -> Conversation: ...

    async def list_conversations(self, context: AIContext) -> list[Conversation]: ...

    async def get_conversation(
        self, context: AIContext, conversation_id: str
    ) -> Conversation | None: ...

    async def list_messages(
        self, context: AIContext, conversation_id: str
    ) -> list[StoredMessage]: ...

    async def add_message(
        self, context: AIContext, conversation_id: str, message: Message
    ) -> StoredMessage: ...

    async def create_action(self, context: AIContext, action: ProposedAction) -> ProposedAction: ...

    async def get_action(self, context: AIContext, action_id: str) -> ProposedAction | None: ...

    async def list_actions(
        self,
        context: AIContext,
        conversation_id: str,
        statuses: Iterable[ActionStatus] | None = None,
    ) -> list[ProposedAction]: ...

    async def update_action(self, context: AIContext, action: ProposedAction) -> ProposedAction: ...


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class InMemoryStore:
    """Dictionaries, scoped by tenant the way the policies would scope rows."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[StoredMessage]] = {}
        self._actions: dict[str, ProposedAction] = {}
        self.usage: list[UsageEvent] = []

    # ── conversations ──────────────────────────────────────────────────────

    async def create_conversation(
        self, context: AIContext, *, agent_id: str, title: str, page: PageContext | None
    ) -> Conversation:
        moment = now()
        conversation = Conversation(
            id=new_id(),
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            agent_id=agent_id,
            title=title,
            created_at=moment,
            updated_at=moment,
            page=page,
        )
        self._conversations[conversation.id] = conversation
        self._messages[conversation.id] = []
        return conversation

    async def list_conversations(self, context: AIContext) -> list[Conversation]:
        return sorted(
            (c for c in self._conversations.values() if c.tenant_id == context.tenant_id),
            key=lambda c: c.updated_at,
            reverse=True,
        )

    async def get_conversation(
        self, context: AIContext, conversation_id: str
    ) -> Conversation | None:
        conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.tenant_id != context.tenant_id:
            return None
        return conversation

    # ── messages ───────────────────────────────────────────────────────────

    async def list_messages(self, context: AIContext, conversation_id: str) -> list[StoredMessage]:
        if await self.get_conversation(context, conversation_id) is None:
            return []
        return list(self._messages.get(conversation_id, []))

    async def add_message(
        self, context: AIContext, conversation_id: str, message: Message
    ) -> StoredMessage:
        conversation = await self.get_conversation(context, conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        stored = StoredMessage(
            id=new_id(),
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            message=message,
            created_at=now(),
        )
        self._messages[conversation_id].append(stored)
        self._conversations[conversation_id] = replace(conversation, updated_at=stored.created_at)
        return stored

    # ── actions ────────────────────────────────────────────────────────────

    async def create_action(self, context: AIContext, action: ProposedAction) -> ProposedAction:
        if action.tenant_id != context.tenant_id:
            raise KeyError(action.id)
        self._actions[action.id] = action
        return action

    async def get_action(self, context: AIContext, action_id: str) -> ProposedAction | None:
        action = self._actions.get(action_id)
        if action is None or action.tenant_id != context.tenant_id:
            return None
        return action

    async def list_actions(
        self,
        context: AIContext,
        conversation_id: str,
        statuses: Iterable[ActionStatus] | None = None,
    ) -> list[ProposedAction]:
        wanted = frozenset(statuses) if statuses is not None else None
        return sorted(
            (
                action
                for action in self._actions.values()
                if action.tenant_id == context.tenant_id
                and action.conversation_id == conversation_id
                and (wanted is None or action.status in wanted)
            ),
            key=lambda action: action.created_at,
        )

    async def update_action(self, context: AIContext, action: ProposedAction) -> ProposedAction:
        if await self.get_action(context, action.id) is None:
            raise KeyError(action.id)
        self._actions[action.id] = action
        return action

    # ── usage ──────────────────────────────────────────────────────────────

    async def record(self, event: UsageEvent) -> None:
        self.usage.append(event)

    async def requests_since(self, tenant_id: str, since: datetime) -> int:
        return sum(1 for e in self.usage if e.tenant_id == tenant_id and e.created_at >= since)


def action_for(
    context: AIContext,
    *,
    conversation_id: str,
    message_id: str | None,
    tool_id: str,
    tool_call_id: str,
    operation: Operation,
    arguments: Mapping[str, Any],
    status: ActionStatus,
) -> ProposedAction:
    """A fresh action row for a proposal the runtime accepted."""
    return ProposedAction(
        id=new_id(),
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        operation=operation,
        input=dict(arguments),
        status=status,
        proposed_by=context.user_id,
        created_at=now(),
    )
