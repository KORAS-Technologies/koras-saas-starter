"""The authorization decisions, made in code and never by a model.

Two questions, asked at two moments.

May this caller have this tool run? Asked when the model proposes a call.
The answer is the tool's permission against the caller's permissions -- the
same closed set the sidebar and the middleware resolve against -- and then
the operation's class: a read runs, anything else waits for a person.

May this caller approve this action? Asked when a person clicks approve. The
answer needs the approve permission and the tool's own permission, so an
approver cannot authorise what they could not have done themselves; a
destructive operation additionally needs an owner or an administrator,
because approving it is the same authority as performing it.

Nothing here reads the conversation. What the model said, however persuasive,
is not an input to either decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from koras_platform import OrganizationRole

from .context import AIContext
from .tools import Operation, ToolDefinition

#: The product permissions this package names. Declared in the product's
#: permission catalogue on both sides of the language boundary; here they are
#: strings compared against the context.
USE_PERMISSION = "ai.use"
APPROVE_PERMISSION = "ai.approve"

_MANAGERS = (OrganizationRole.OWNER.value, OrganizationRole.ADMIN.value)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool
    #: Why not, when not. Safe to log; never shown with the permission name.
    reason: str = ""


def decide(tool: ToolDefinition, context: AIContext) -> Decision:
    """Whether the caller may have this tool run, and whether a person must agree first."""
    if not context.holds(USE_PERMISSION):
        return Decision(allowed=False, requires_approval=False, reason="caller may not use AI")
    if not context.holds(tool.permission):
        return Decision(
            allowed=False,
            requires_approval=False,
            reason=f"caller lacks the permission {tool.id} needs",
        )
    return Decision(allowed=True, requires_approval=tool.requires_approval)


def may_decide(tool: ToolDefinition, context: AIContext) -> Decision:
    """Whether the caller may approve or reject a waiting action for this tool."""
    if not context.holds(APPROVE_PERMISSION):
        return Decision(allowed=False, requires_approval=True, reason="caller may not approve")
    if not context.holds(tool.permission):
        return Decision(
            allowed=False,
            requires_approval=True,
            reason="approver lacks the permission the tool needs",
        )
    if tool.operation is Operation.DESTRUCTIVE and not context.has_any_role(*_MANAGERS):
        return Decision(
            allowed=False,
            requires_approval=True,
            reason="a destructive action needs an owner or administrator",
        )
    return Decision(allowed=True, requires_approval=True)


def visible_tools(
    tools: tuple[ToolDefinition, ...], context: AIContext, *, tools_enabled: bool
) -> tuple[ToolDefinition, ...]:
    """The tools the model is told about for this caller.

    Filtered by permission before the model ever sees them, so it is not
    invited to propose what would be refused. The refusal at execution stays:
    this narrows what is offered, it is not the check.
    """
    if not tools_enabled:
        return ()
    return tuple(tool for tool in tools if decide(tool, context).allowed)
