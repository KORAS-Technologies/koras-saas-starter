"""The approval notice: who is told, what they are told, and what is never in it."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_ai import ActionStatus, Operation, ProposedAction  # noqa: E402
from koras_api.core import notify  # noqa: E402
from koras_email import RecordingEmailSender  # noqa: E402


def _action(status: ActionStatus = ActionStatus.AWAITING_APPROVAL) -> ProposedAction:
    return ProposedAction(
        id="act-1",
        tenant_id="tenant-1",
        conversation_id="conv-1",
        message_id=None,
        tool_id="files.delete",
        tool_call_id="call-1",
        operation=Operation.DESTRUCTIVE,
        input={"name": "quarterly-figures.xlsx"},
        status=status,
        proposed_by="user-owner",
        created_at=datetime.now(UTC),
    )


def test_only_owners_and_administrators_who_are_active_are_told() -> None:
    members = [
        {"email": "Owner@Acme.test", "role": "organization_owner", "status": "active"},
        {"email": "admin@acme.test", "role": "organization_admin", "status": "active"},
        {"email": "invited@acme.test", "role": "organization_admin", "status": "invited"},
        {"email": "member@acme.test", "role": "member", "status": "active"},
        {"email": "billing@acme.test", "role": "billing_admin", "status": "active"},
        {"role": "organization_owner", "status": "active"},
        "not a member",
    ]
    assert notify.approvers_from_members(members) == ["owner@acme.test", "admin@acme.test"]
    assert notify.approvers_from_members({"members": []}) == []


def test_the_notice_names_the_tool_and_never_its_input() -> None:
    subject, body = notify.compose(
        [_action()], product="Sample", app_url="https://app.example.test/"
    )
    assert "waiting for approval" in subject
    assert "files.delete" in body and "destructive" in body
    assert "user-owner" in body
    assert "https://app.example.test/dashboard/assistant" in body
    # The proposal's input is the model's guess at a customer's data; it
    # stays in the conversation and out of every inbox.
    assert "quarterly-figures" not in body


async def test_one_notice_per_approver_and_none_when_nothing_waits() -> None:
    sender = RecordingEmailSender()
    sent = await notify.notify_awaiting_approval(
        recipients=["owner@acme.test", "admin@acme.test"],
        actions=[_action(), _action(ActionStatus.COMPLETED)],
        product="Sample",
        app_url="",
        sender=sender,
    )
    assert sent == 2
    assert [m["to"] for m in sender.sent] == ["owner@acme.test", "admin@acme.test"]
    assert sender.sent[0]["tag"] == "ai-approval:act-1"
    assert "the assistant page" in sender.sent[0]["body"]

    quiet = RecordingEmailSender()
    assert (
        await notify.notify_awaiting_approval(
            recipients=["owner@acme.test"],
            actions=[_action(ActionStatus.COMPLETED)],
            product="Sample",
            app_url="",
            sender=quiet,
        )
        == 0
    )
    assert quiet.sent == []


async def test_approvers_come_from_the_owner_row_and_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        async def execute(self, statement: object, parameters: object) -> _Session:
            return self

        def scalar_one_or_none(self) -> str:
            return "Owner@Acme.test"

    class _Answer:
        body = [{"email": "admin@acme.test", "role": "organization_admin", "status": "active"}]

    async def _read_portal(path: str, *, organization_id: str, token: str) -> _Answer:
        assert path.endswith("/members") and token == "tok"  # noqa: S105
        return _Answer()

    monkeypatch.setattr(notify.platform, "configured", lambda: True)
    monkeypatch.setattr(notify.platform, "read_portal", _read_portal)
    found = await notify.approvers(
        _Session(),  # type: ignore[arg-type]
        tenant_id="tenant-1",
        organization_id="org-1",
        token="tok",  # noqa: S106
    )
    assert found == ["owner@acme.test", "admin@acme.test"]
