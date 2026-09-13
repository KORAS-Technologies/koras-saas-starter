"""What can go wrong, named so a caller can act on it.

One exception type with a code, rather than a class per failure, because the
callers that matter -- the API router and the web tier -- dispatch on the code
and nothing else. Each code maps to one HTTP status and one sentence in the
customer's language; the mapping lives beside the router.

Two messages, on purpose. `message` is safe to show: it says what the caller
can do about it and names no provider, no key, no host and no stack. `detail`
is for the log: the upstream status, the exception class, the route that was
tried. A refusal that leaked the second into the first would tell a customer
which provider their data went to, which is the platform's decision to
disclose and not this package's.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    AI_DISABLED = "ai_disabled"
    ENTITLEMENT_MISSING = "entitlement_missing"
    USAGE_EXCEEDED = "usage_exceeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_MODEL_ALIAS = "invalid_model_alias"
    TOOL_DENIED = "tool_denied"
    APPROVAL_REQUIRED = "approval_required"
    UNREGISTERED_ACTION = "unregistered_action"
    RETRIEVAL_FAILED = "retrieval_failed"
    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    CONFIGURATION_ERROR = "configuration_error"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"


class AIError(Exception):
    """A refusal or a failure the AI runtime can name.

    `message` is what a customer may read. `detail` is what the log gets.
    """

    def __init__(self, code: ErrorCode, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


def disabled(message: str = "AI is not enabled for this product") -> AIError:
    return AIError(ErrorCode.AI_DISABLED, message)


def not_entitled(entitlement: str) -> AIError:
    return AIError(
        ErrorCode.ENTITLEMENT_MISSING,
        f"this organization's plan does not include {entitlement}",
    )


def usage_exceeded(limit: int) -> AIError:
    return AIError(
        ErrorCode.USAGE_EXCEEDED,
        f"the plan's monthly allowance of {limit} AI requests is spent",
    )


def invalid_alias(alias: str) -> AIError:
    return AIError(ErrorCode.INVALID_MODEL_ALIAS, f"{alias!r} is not a model alias")


def tool_denied(tool_id: str) -> AIError:
    # Says which tool and not which permission: naming the permission tells
    # somebody probing which ones exist and which are worth acquiring.
    return AIError(ErrorCode.TOOL_DENIED, f"this account may not use {tool_id}")


def unregistered(tool_id: str) -> AIError:
    return AIError(ErrorCode.UNREGISTERED_ACTION, f"{tool_id!r} is not a registered tool")


def configuration(message: str, *, detail: str | None = None) -> AIError:
    return AIError(ErrorCode.CONFIGURATION_ERROR, message, detail=detail)


def not_found(what: str) -> AIError:
    return AIError(ErrorCode.NOT_FOUND, f"no such {what}")


def invalid_state(message: str) -> AIError:
    return AIError(ErrorCode.INVALID_STATE, message)
