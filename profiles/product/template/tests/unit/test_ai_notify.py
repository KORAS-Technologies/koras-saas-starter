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
from koras_api.core import dispatch, notify, recipients  # noqa: E402
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


class _Members:
    """A session that answers the two reads `recipients.resolve` makes."""

    def __init__(
        self,
        members: list[tuple[str, str]],
        member_settings: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._members = members
        self._settings = member_settings or {}
        self.reads: list[str] = []

    async def execute(self, statement: object, parameters: dict[str, Any]) -> Any:  # noqa: ANN401
        sql = str(statement)
        self.reads.append(sql)
        if "tenant_members" in sql:
            rows = [
                type("Row", (), {"user_id": user, "role": role})()
                for user, role in self._members
            ]
            return type("Result", (), {"all": lambda _self: rows})()
        if "owner_email" in sql:
            return type("Result", (), {"scalar_one_or_none": lambda _self: "Owner@Acme.test"})()
        # The member settings read, which `settings_store.member_values` makes
        # and which unpacks each row as a (key, value) pair.
        user = parameters.get("user_id", "")
        pairs = list(self._settings.get(str(user), {}).items())
        return type("Result", (), {"all": lambda _self: pairs})()


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
    # Moved to `core/recipients.py` in CAT-01 Phase 2 and given the permission
    # as an argument: it was hardcoded to `ai.approve` in a module the
    # assistant owns, which is the wrong place for a rule any producer needs.
    assert recipients.addresses_from_members(members, "ai.approve") == [
        "owner@acme.test",
        "admin@acme.test",
    ]
    assert recipients.addresses_from_members({"members": []}, "ai.approve") == []
    # A different permission resolves a different audience, which is the
    # whole point of taking it as an argument: the billing administrator holds
    # `reports.export` and does not hold `ai.approve`.
    assert "billing@acme.test" in recipients.addresses_from_members(
        members, "reports.export"
    )


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


async def test_the_mail_dispatch_prepared_is_sent_once_per_address() -> None:
    """`dispatch` prepares; `send` delivers. The split is so that a mail leaves
    only after the caller's transaction has committed — a feed row can be
    rolled back and a mail cannot."""
    sender = RecordingEmailSender()
    mail = [
        dispatch.Mail(
            to="owner@acme.test",
            subject="Sample: an action is waiting",
            text="Go to the assistant page.",
            html="<p>Delete the file a.md</p>",
            tag="ai.approval_requested",
        ),
        dispatch.Mail(
            to="admin@acme.test",
            subject="Sample: an action is waiting",
            text="Go to the assistant page.",
            html="<p>Delete the file a.md</p>",
            tag="ai.approval_requested",
        ),
    ]
    assert await dispatch.send(sender, mail) == 2
    assert [m["to"] for m in sender.sent] == ["owner@acme.test", "admin@acme.test"]
    assert sender.sent[0]["tag"] == "ai.approval_requested"
    assert "Delete the file a.md" in (sender.sent[0]["html"] or "")

    quiet = RecordingEmailSender()
    assert await dispatch.send(quiet, []) == 0
    assert quiet.sent == []


async def test_a_send_that_fails_does_not_stop_the_rest() -> None:
    """The thing the customer asked for has already happened by the time these
    go out. One provider refusal must not cost the other nine their notice."""

    class _Flaky:
        def __init__(self) -> None:
            self.seen: list[str] = []

        @property
        def simulated(self) -> bool:
            return False

        async def send(self, *, to: str, **_: object) -> object:
            self.seen.append(to)
            if to == "bad@acme.test":
                raise RuntimeError("the provider refused")
            return type("Sent", (), {"simulated": False})()

    sender = _Flaky()
    mail = [
        dispatch.Mail(to=address, subject="s", text="t", html="<p>h</p>")
        for address in ("bad@acme.test", "good@acme.test")
    ]
    assert await dispatch.send(sender, mail) == 1  # type: ignore[arg-type]
    assert sender.seen == ["bad@acme.test", "good@acme.test"]


def test_the_approval_template_says_the_same_thing_in_both_bodies() -> None:
    """The feed used to take the mail's first line by splitting the plain text.
    That worked, and would have stopped working the first time the mail grew a
    preamble. One template renders both now."""
    summary = notify.ActionSummary("files.delete", "destructive", "Delete the file a.md", "1 KB")
    render = notify.approval_notice(
        [summary],
        product="Sample",
        app_url="",
        requester=REQUESTER,
        request_text="delete a.md",
        requested_at=WHEN,
    )
    english = render("en")
    assert english.title == english.subject
    assert english.url == "/dashboard/assistant"
    assert english.html is not None and "Delete the file a.md" in english.html
    assert english.body and english.body in english.text

    # A language in, that language out. The one thing a template is for.
    german = render("de")
    assert german.subject != english.subject


async def test_an_audience_resolves_the_owner_and_the_platforms_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One rule, both halves. The owner contributes an address with no subject,
    because the tenant row holds the address and not the person."""

    class _Answer:
        body = [{"email": "admin@acme.test", "role": "organization_admin", "status": "active"}]

    async def _read_portal(path: str, *, organization_id: str, token: str) -> _Answer:
        assert path.endswith("/members") and token == "tok"  # noqa: S105
        return _Answer()

    monkeypatch.setattr(recipients.platform, "configured", lambda: True)
    monkeypatch.setattr(recipients.platform, "read_portal", _read_portal)

    found = await recipients.resolve(
        _Members([]),  # type: ignore[arg-type]
        tenant_id="tenant-1",
        audience=recipients.Audience(permission="ai.approve", include_owner=True),
        organization_id="org-1",
        token="tok",  # noqa: S106
    )
    assert sorted(person.email or "" for person in found) == [
        "admin@acme.test",
        "owner@acme.test",
    ]
    # Neither has a subject, so neither gets a feed row. That is the asymmetry
    # `recipients.py` exists to make visible rather than paper over.
    assert recipients.subjects_of(found) == []


async def test_a_member_is_resolved_with_their_own_language() -> None:
    """NOTIF-DEF-003. The notice went out in the language of the person who
    asked, who is the one person it is never sent to."""
    session = _Members(
        [("user-1", "organization_admin"), ("user-2", "member")],
        member_settings={"user-1": {"general.language": "de"}},
    )
    found = await recipients.resolve(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        audience=recipients.Audience(permission="ai.approve"),
        fallback_locale="es",
    )
    assert [(p.subject, p.locale, p.locale_is_theirs) for p in found] == [
        ("user-1", "de", True)
    ]


async def test_a_member_with_no_stored_language_falls_back_to_the_organisation() -> None:
    session = _Members([("user-1", "organization_admin")])
    [person] = await recipients.resolve(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        audience=recipients.Audience(permission="ai.approve"),
        fallback_locale="es",
    )
    assert (person.locale, person.locale_is_theirs) == ("es", False)


async def test_auto_is_not_a_language_to_write_in() -> None:
    """ADR 0007 makes `auto` a value rather than an absence, and there is no
    context to infer from in a background send."""
    session = _Members(
        [("user-1", "organization_admin")],
        member_settings={"user-1": {"general.language": "auto"}},
    )
    [person] = await recipients.resolve(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        audience=recipients.Audience(permission="ai.approve"),
        fallback_locale="de",
    )
    assert (person.locale, person.locale_is_theirs) == ("de", False)


def test_an_audience_that_names_nobody_is_refused_at_the_call_site() -> None:
    """A rule resolving to nobody is a question for the caller; a rule that
    *cannot* resolve to anybody is a bug, and fails where it is written."""
    with pytest.raises(ValueError, match="say who it is for"):
        recipients.Audience()
