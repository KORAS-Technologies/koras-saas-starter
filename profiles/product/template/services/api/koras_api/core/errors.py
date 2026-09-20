"""One shape for every refusal: a stable code, and a sentence for the log.

The assistant's routes answered `{"code": ..., "message": ...}` from the day
they existed, so the page could say *why* in the reader's language -- a
spent allowance and an unreachable model are both errors and are different
sentences. Every other route answered a plain English `detail`, and the web
tier mapped the *status* to its own message, which is coarser than it looks:
a 402 on the files page is "your plan does not include this" and also "this
upload would exceed your storage", and only the English string told them
apart.

This is the same shape for the whole API. `code` is the contract: a short,
stable, snake_case name the web tier maps to a catalogue key and renders in
the visitor's language. `message` is for the log, the terminal and the
engineer reading a response by hand; it is English, it is not shown to a
person, and it may change without notice. Nothing else goes in `detail`,
because anything else becomes a second contract by accident.

Codes are listed here rather than typed inline so a route cannot invent
one that nothing on the web side knows. Adding a code means adding it to
`packages/i18n` as `errors.<code>` in every language the product offers;
the structural test in the starter reads both lists.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from fastapi import HTTPException


class ApiErrorCode(StrEnum):
    """Every refusal a route of this API can answer with, by name."""

    # who is asking
    TOKEN_INVALID = "token_invalid"  # noqa: S105 - an error code, not a credential
    TENANT_INACTIVE = "tenant_inactive"
    ROLE_REQUIRED = "role_required"
    PERMISSION_MISSING = "permission_missing"
    # what the plan includes
    ENTITLEMENT_MISSING = "entitlement_missing"
    STORAGE_LIMIT_EXCEEDED = "storage_limit_exceeded"
    # files
    FILE_NOT_FOUND = "file_not_found"
    UPLOAD_NOT_ARRIVED = "upload_not_arrived"
    UPLOAD_SIZE_MISMATCH = "upload_size_mismatch"
    FILE_QUARANTINED = "file_quarantined"
    FILE_UNDER_HOLD = "file_under_hold"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    UPLOAD_REFUSED_BY_POLICY = "upload_refused_by_policy"
    # reporting
    REPORT_NOT_FOUND = "report_not_found"
    SCHEDULE_NOT_FOUND = "schedule_not_found"
    EXPORT_NOT_FOUND = "export_not_found"
    EXPORT_FORMAT_UNKNOWN = "export_format_unknown"
    EXPORT_FORMAT_UNSUPPORTED = "export_format_unsupported"
    FILTER_INVALID = "filter_invalid"
    RECIPIENT_INVALID = "recipient_invalid"
    PERIOD_NOT_A_FILTER = "period_not_a_filter"
    REPORT_FAILED = "report_failed"
    # legal holds and audit search
    HOLD_NOT_FOUND = "hold_not_found"
    HOLD_NOT_TRANSITIONABLE = "hold_not_transitionable"
    HOLD_INVALID_WINDOW = "hold_invalid_window"
    AUDIT_EVENT_NOT_FOUND = "audit_event_not_found"
    # restoring an object from its backup
    BACKUP_NOT_FOUND = "backup_not_found"
    RESTORE_NOT_FOUND = "restore_not_found"
    RESTORE_NOT_TRANSITIONABLE = "restore_not_transitionable"
    RESTORE_ALREADY_REQUESTED = "restore_already_requested"
    RESTORE_OVERWRITE_UNCONFIRMED = "restore_overwrite_unconfirmed"
    # data import
    IMPORT_TARGET_NOT_FOUND = "import_target_not_found"
    IMPORT_RUN_NOT_FOUND = "import_run_not_found"
    IMPORT_MAPPING_REFUSED = "import_mapping_refused"
    IMPORT_FILE_UNREADABLE = "import_file_unreadable"
    IMPORT_TOO_MANY_ROWS = "import_too_many_rows"
    IMPORT_OPERATION_REFUSED = "import_operation_refused"
    IMPORT_NOT_TRANSITIONABLE = "import_not_transitionable"
    IMPORT_QUEUE_UNAVAILABLE = "import_queue_unavailable"
    IMPORT_NOT_COMMITTABLE = "import_not_committable"
    IMPORT_FILE_TOO_LARGE = "import_file_too_large"
    # notifications
    NOTIFICATION_NOT_FOUND = "notification_not_found"
    # settings
    SETTING_NOT_FOUND = "setting_not_found"
    SETTING_VALUE_INVALID = "setting_value_invalid"
    SETTING_SCOPE_REFUSED = "setting_scope_refused"
    # the assistant (its own errors carry `koras_ai.ErrorCode`; this one is the API's)
    TOOL_DENIED = "tool_denied"
    # the platform's private contract: machine callers, never a person
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    SLUG_TAKEN = "slug_taken"
    TENANT_NOT_FOUND = "tenant_not_found"
    MACHINE_IDENTITY_REQUIRED = "machine_identity_required"
    PLATFORM_CALLER_REQUIRED = "platform_caller_required"
    PLATFORM_CALLER_UNCONFIGURED = "platform_caller_unconfigured"


def api_error(
    status_code: int,
    code: ApiErrorCode,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> HTTPException:
    """The refusal a route raises: `raise api_error(404, ApiErrorCode.FILE_NOT_FOUND, "...")`.

    Returned rather than raised so `raise ... from exc` reads naturally at
    the call site, and so a test can build one to compare against.
    """
    return HTTPException(
        status_code=status_code,
        detail={"code": code.value, "message": message},
        headers=dict(headers) if headers else None,
    )


__all__ = ["ApiErrorCode", "api_error"]
