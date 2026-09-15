"""The approval notice: who is told, what they are told, and what is never in it."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_ai import ActionStatus, Operation, ProposedAction  # noqa: E402
from koras_api.core import notify  # noqa: E402
from koras_email import RecordingEmailSender  # noqa: E402

FILE_ID = "31055174-7afb-4a70-8e3b-1bb0b5dd250b"
REQUESTER = notify.Requester(id="390639721715368755", name="Kora K", email="kora@acme.test")
WHEN = datetime(2026, 9, 14, 15, 6, tzinfo=UTC)


def _action(
    status: ActionStatus = ActionStatus.AWAITING_APPROVAL,
    tool_id: str = "files.delete",
    arguments: dict[str, Any] | None = None,
) -> ProposedAction:
    return ProposedAction(
        id="act-1",
        tenant_id="tenant-1",
        conversation_id="conv-1",
        message_id=None,
        tool_id=tool_id,
        tool_call_id="call-1",
        operation=Operation.DESTRUCTIVE,
        input=arguments if arguments is not None else {"file_id": FILE_ID},
        status=status,
        proposed_by="390639721715368755",
        created_at=WHEN,
    )


class _FileRow:
    name = "AI_FOUNDATION_PLAN.md"
    size_bytes = 16804
    ready_at = datetime(2026, 9, 14, 14, 23, tzinfo=UTC)


class _Session:
    def __init__(self, row: object | None) -> None:
        self._row = row
        self.parameters: list[dict[str, Any]] = []

    async def execute(self, statement: object, parameters: dict[str, Any]) -> _Session:
        self.parameters.append(parameters)
        return self

    def first(self) -> object | None:
        return self._row

    def scalar_one_or_none(self) -> str:
        return "Owner@Acme.test"


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


async def test_a_delete_is_described_by_the_file_it_would_delete() -> None:
    session = _Session(_FileRow())
    [summary] = await notify.summarize(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        actions=[_action()],
    )
    assert summary.title == "Delete the file AI_FOUNDATION_PLAN.md"
    assert summary.detail == "17 KB, uploaded 14 Sep 2026"
    assert summary.operation == "destructive"
    # The lookup is scoped to the tenant the action belongs to.
    assert session.parameters[0]["tenant_id"] == "tenant-1"


async def test_an_unknown_file_and_an_unknown_tool_still_read_as_words() -> None:
    [gone] = await notify.summarize(
        _Session(None),  # type: ignore[arg-type]
        tenant_id="tenant-1",
        actions=[_action()],
    )
    assert gone.title == "Delete a file" and FILE_ID in gone.detail

    [other] = await notify.summarize(
        None,
        tenant_id="tenant-1",
        actions=[_action(tool_id="files.rename", arguments={"file_id": FILE_ID, "name": "new.md"})],
    )
    assert other.title == "Run files.rename, which deletes something"
    assert "name: new.md" in other.detail


def test_the_notice_says_who_asked_what_and_where_to_decide() -> None:
    summary = notify.ActionSummary(
        tool_id="files.delete",
        operation="destructive",
        title="Delete the file AI_FOUNDATION_PLAN.md",
        detail="17 KB, uploaded 14 Sep 2026",
    )
    subject, body, html = notify.compose(
        [summary],
        product="Koras E2E Shop",
        app_url="https://app.example.test/",
        requester=REQUESTER,
        request_text="delete the file AI_FOUNDATION_PLAN.md",
        requested_at=WHEN,
    )
    assert subject == "[Koras E2E Shop] Approval needed: Delete the file AI_FOUNDATION_PLAN.md"
    for text in (body, html):
        assert "Kora K (kora@acme.test)" in text
        assert "delete the file AI_FOUNDATION_PLAN.md" in text
        assert "Delete the file AI_FOUNDATION_PLAN.md" in text
        assert "17 KB, uploaded 14 Sep 2026" in text
        assert "https://app.example.test/dashboard/assistant" in text
        assert "has not run" in text
        assert "14 Sep 2026, 15:06 UTC" in text
    # The subject id is never the way a person is named.
    assert "390639721715368755" not in body and "390639721715368755" not in html
    assert html.startswith("<!doctype html>") and "Review and decide" in html


def test_the_notice_is_written_in_the_language_asked_for() -> None:
    """The same notice, in German: the sentences change, the facts do not."""
    summary = notify.ActionSummary(
        "files.delete", "destructive", "Delete the file AI_FOUNDATION_PLAN.md", "17 KB"
    )
    subject, body, html = notify.compose(
        [summary],
        product="Koras E2E Shop",
        app_url="https://app.example.test/",
        requester=REQUESTER,
        request_text="delete the file AI_FOUNDATION_PLAN.md",
        requested_at=WHEN,
        locale="de",
    )
    assert subject == (
        "[Koras E2E Shop] Freigabe erforderlich: Delete the file AI_FOUNDATION_PLAN.md"
    )
    for text in (body, html):
        assert "Kora K (kora@acme.test)" in text
        assert "https://app.example.test/dashboard/assistant" in text
        assert "Es wurde nicht ausgeführt" in text
        assert "14.09.2026, 15:06 UTC" in text
        assert "Approval needed" not in text and "has not run" not in text
    assert "Prüfen und entscheiden</a>" in html and "Freigabe erforderlich</td>" in html


def test_html_escapes_what_a_person_typed() -> None:
    summary = notify.ActionSummary("files.delete", "destructive", "Delete the file <x>.md", "")
    _subject, _body, html = notify.compose(
        [summary],
        product="P",
        app_url="",
        requester=notify.Requester(id="1", name="<script>alert(1)</script>"),
        request_text="<b>bold</b>",
        requested_at=WHEN,
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>bold</b>" not in html and "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "&lt;x&gt;.md" in html


async def test_one_notice_per_approver_with_an_html_body_and_none_when_nothing_waits() -> None:
    sender = RecordingEmailSender()
    summary = notify.ActionSummary("files.delete", "destructive", "Delete the file a.md", "1 KB")
    sent = await notify.notify_awaiting_approval(
        recipients=["owner@acme.test", "admin@acme.test"],
        summaries=[summary],
        product="Sample",
        app_url="",
        requester=REQUESTER,
        request_text="delete a.md",
        requested_at=WHEN,
        tag="ai-approval:act-1",
        sender=sender,
    )
    assert sent == 2
    assert [m["to"] for m in sender.sent] == ["owner@acme.test", "admin@acme.test"]
    assert sender.sent[0]["tag"] == "ai-approval:act-1"
    assert sender.sent[0]["html"] is not None and "Delete the file a.md" in sender.sent[0]["html"]
    assert "assistant page" in sender.sent[0]["body"]

    quiet = RecordingEmailSender()
    assert (
        await notify.notify_awaiting_approval(
            recipients=["owner@acme.test"],
            summaries=[],
            product="Sample",
            app_url="",
            requester=REQUESTER,
            request_text="",
            sender=quiet,
        )
        == 0
    )
    assert quiet.sent == []


async def test_approvers_come_from_the_owner_row_and_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Answer:
        body = [{"email": "admin@acme.test", "role": "organization_admin", "status": "active"}]

    async def _read_portal(path: str, *, organization_id: str, token: str) -> _Answer:
        assert path.endswith("/members") and token == "tok"  # noqa: S105
        return _Answer()

    monkeypatch.setattr(notify.platform, "configured", lambda: True)
    monkeypatch.setattr(notify.platform, "read_portal", _read_portal)
    found = await notify.approvers(
        _Session(None),  # type: ignore[arg-type]
        tenant_id="tenant-1",
        organization_id="org-1",
        token="tok",  # noqa: S106
    )
    assert found == ["owner@acme.test", "admin@acme.test"]
