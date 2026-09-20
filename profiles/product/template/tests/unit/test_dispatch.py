"""What the dispatch point does, and the three things it must never do.

CAT-01 Phase 2. Before it, the starter's one producer wrote its own feed row,
resolved its own audience twice, composed its own HTML and sent its own mail,
and none of that consulted a preference. The exit criterion for this phase is
one sentence — *switching off notification emails switches off notification
emails* — and it is the first test below.

Three properties, each invisible in a happy-path test:

**A preference is honoured per person.** Not per organisation, not per send. Two
people in the same organisation with different answers get different outcomes
from one `dispatch` call.

**A channel refusal is not a failure.** Somebody who has switched email off is
skipped and counted, and the feed row still goes out. Getting this backwards
means one person's preference silences a notification for everybody.

**Mail is prepared, never sent here.** A feed row can be rolled back and a mail
cannot, so `dispatch` returns the mail and the caller sends it after its commit.
A `dispatch` that sent would put an unrecallable message inside a transaction
that may not commit.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Before the first import of anything that reads settings. The same preamble
# `test_settings_api.py` uses, and for the same reason: importing the catalogue
# pulls in `core/settings.py`, which refuses to construct without these.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core import dispatch  # noqa: E402
from koras_api.core.dispatch import Event, Rendered  # noqa: E402
from koras_api.core.notifications import NotificationKind, kinds  # noqa: E402
from koras_api.core.recipients import Audience  # noqa: E402

pytestmark = pytest.mark.asyncio

TEST_KIND = NotificationKind(
    key="test.something_happened",
    summary="A kind that exists only for this file.",
    default_severity="info",
)
if TEST_KIND.key not in kinds:
    kinds.add(TEST_KIND)


def render(locale: str) -> Rendered:
    """A template with both forms, so both channels have something to do."""
    return Rendered(
        title=f"title-{locale}",
        body=f"body-{locale}",
        url="/dashboard",
        subject=f"subject-{locale}",
        text=f"text-{locale}",
        html=f"<p>{locale}</p>",
    )


def feed_only(locale: str) -> Rendered:
    """A template with no mail form. How a kind becomes in-app only."""
    return Rendered(title=f"title-{locale}", body="", url="/dashboard")


class _Session:
    """A session that answers the reads dispatch makes, and records the writes.

    Settings are answered per scope so a test can put the platform, the
    organisation and a person in disagreement, which is the only way to check
    that the resolver rather than a row is what decides.
    """

    def __init__(
        self,
        members: list[tuple[str, str]],
        *,
        owner: str | None = None,
        global_settings: dict[str, Any] | None = None,
        tenant_settings: dict[str, Any] | None = None,
        member_settings: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._members = members
        self._owner = owner
        self._global = global_settings or {}
        self._tenant = tenant_settings or {}
        self._member = member_settings or {}
        self.written: list[dict[str, Any]] = []

    async def execute(self, statement: object, parameters: Any = None) -> Any:  # noqa: ANN401
        sql = str(statement)
        params = dict(parameters or {})

        if "tenant_members" in sql:
            rows = [
                type("Row", (), {"user_id": user, "role": role})()
                for user, role in self._members
            ]
            return type("R", (), {"all": lambda _s: rows})()
        if "owner_email" in sql:
            owner = self._owner
            return type("R", (), {"scalar_one_or_none": lambda _s: owner})()
        if "global_settings" in sql:
            return type("R", (), {"all": lambda _s: list(self._global.items())})()
        if "tenant_setting_values" in sql:
            return type("R", (), {"all": lambda _s: list(self._tenant.items())})()
        if "member_setting_values" in sql:
            stored = self._member.get(str(params.get("user_id", "")), {})
            return type("R", (), {"all": lambda _s: list(stored.items())})()
        if "insert into public.notifications" in sql:
            self.written.append(params)
            return type("R", (), {"all": lambda _s: [object()]})()
        return type("R", (), {"all": lambda _s: [], "first": lambda _s: None})()

    async def commit(self) -> None:
        return None


class _Counting(_Session):
    """Records which tables were read, so a cost can be asserted."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.statements: list[str] = []

    async def execute(self, statement: object, parameters: Any = None) -> Any:  # noqa: ANN401
        self.statements.append(str(statement))
        return await super().execute(statement, parameters)

    def tally(self) -> dict[str, int]:
        names = (
            "global_settings",
            "tenant_setting_values",
            "member_setting_values",
            "tenant_members",
        )
        found = dict.fromkeys(names, 0)
        for sql in self.statements:
            for name in names:
                if name in sql:
                    found[name] += 1
        return found


def _event(session_free: Audience | None = None, **kw: Any) -> Event:  # noqa: ANN401
    return Event(
        kind=TEST_KIND.key,
        tenant_id="11111111-1111-1111-1111-111111111111",
        audience=session_free or Audience(permission="settings.read"),
        render=kw.pop("render", render),
        **kw,
    )


# ── the exit criterion ───────────────────────────────────────────────────────


async def test_switching_off_notification_emails_switches_off_notification_emails() -> None:
    """The sentence CAT-01 Phase 2 exists to make true.

    `notifications.emailEnabled` was declared, translated into three languages,
    drawn on the preferences page, and read by nothing at all: a customer could
    switch it off and go on receiving mail.

    **At the organisation level, which is the only level it has.** The setting
    was `GLOBAL_ORG_USER` and is `GLOBAL_ORG` now: a mail goes to an address,
    the product learns addresses from the platform's member list, and that list
    carries no subject — so a recipient it can mail is one it cannot match to a
    member, and a person-level switch could never be read. Offering the rung
    anyway would be the same mistake `surfaced=False` exists to prevent.
    """
    off = _Session([], owner="owner@acme.test", tenant_settings={dispatch.EMAIL_SETTING: False})
    quiet = await dispatch.dispatch(
        off,  # type: ignore[arg-type]
        _event(session_free=Audience(include_owner=True)),
    )
    assert quiet.mail == ()
    assert "owner@acme.test:email_off" in quiet.skipped

    # And with it on, the same call produces the mail — so the assertion above
    # is about the switch rather than about the audience being empty.
    on = _Session([], owner="owner@acme.test")
    loud = await dispatch.dispatch(
        on,  # type: ignore[arg-type]
        _event(session_free=Audience(include_owner=True)),
    )
    assert [mail.to for mail in loud.mail] == ["owner@acme.test"]


async def test_a_member_with_no_address_gets_the_feed_and_no_mail() -> None:
    """The common case today, and the asymmetry `recipients.py` documents: the
    product knows its members as subjects and its addresses as addresses, and
    the two do not join."""
    session = _Session([("user-1", "organization_admin"), ("user-2", "organization_admin")])
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome.in_app == 2
    assert outcome.mail == ()
    assert sorted(outcome.skipped) == ["user-1:no_address", "user-2:no_address"]


async def test_an_email_preference_does_not_touch_the_feed() -> None:
    """Two channels, two switches. Somebody who wants no mail still gets the
    notification — turning one off must not silently turn the other off."""
    session = _Session(
        [("user-1", "organization_admin")],
        owner="owner@acme.test",
        tenant_settings={dispatch.EMAIL_SETTING: False},
    )
    outcome = await dispatch.dispatch(
        session,  # type: ignore[arg-type]
        _event(session_free=Audience(permission="settings.read", include_owner=True)),
    )
    assert outcome.mail == ()
    assert "owner@acme.test:email_off" in outcome.skipped
    assert outcome.in_app == 1


async def test_the_organisation_can_be_overridden_by_a_person() -> None:
    """Three levels, and the middle one losing to the one above it is the whole
    point of resolving rather than reading a row."""
    session = _Session(
        [("user-1", "organization_admin")],
        tenant_settings={dispatch.IN_APP_SETTING: False},
        member_settings={"user-1": {dispatch.IN_APP_SETTING: True}},
    )
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome.in_app == 1
    assert not any(reason.endswith(":in_app_off") for reason in outcome.skipped)


async def test_one_persons_preference_does_not_silence_another() -> None:
    session = _Session(
        [("user-quiet", "organization_admin"), ("user-loud", "organization_admin")],
        member_settings={"user-quiet": {dispatch.IN_APP_SETTING: False}},
    )
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome.recipients == 2
    assert outcome.in_app == 1
    assert "user-quiet:in_app_off" in outcome.skipped


# ── mail is prepared, not sent ───────────────────────────────────────────────


async def test_mail_is_returned_rather_than_sent() -> None:
    """A feed row can be rolled back and a mail cannot, so the send waits for
    the caller's commit."""
    session = _Session([], owner="owner@acme.test")
    outcome = await dispatch.dispatch(
        session,  # type: ignore[arg-type]
        _event(session_free=Audience(include_owner=True)),
    )
    assert [mail.to for mail in outcome.mail] == ["owner@acme.test"]
    assert outcome.mail[0].tag == TEST_KIND.key
    assert outcome.mail[0].subject == "subject-en"


async def test_a_template_with_no_mail_form_sends_none() -> None:
    """How a kind becomes in-app only: a property of the template rather than a
    flag somewhere else."""
    session = _Session(
        [("user-1", "organization_admin")], owner="owner@acme.test"
    )
    outcome = await dispatch.dispatch(
        session,  # type: ignore[arg-type]
        _event(
            session_free=Audience(permission="settings.read", include_owner=True),
            render=feed_only,
        ),
    )
    assert outcome.in_app == 1
    assert outcome.mail == ()
    assert "owner@acme.test:no_mail_form" in outcome.skipped


# ── languages ────────────────────────────────────────────────────────────────


async def test_each_person_is_written_to_in_their_own_language() -> None:
    """NOTIF-DEF-003. The notice used to go out in the language of the person
    who asked, who is the one person it is never sent to."""
    session = _Session(
        [("user-de", "organization_admin"), ("user-es", "organization_admin")],
        member_settings={
            "user-de": {"general.language": "de"},
            "user-es": {"general.language": "es"},
        },
    )
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome.in_app == 2
    titles = sorted(row["title"] for row in session.written)
    assert titles == ["title-de", "title-es"]


async def test_one_rendering_per_language_not_per_person() -> None:
    """Two people who share a language provably see the same words, and the
    template is called once for them rather than twice."""
    calls: list[str] = []

    def counting(locale: str) -> Rendered:
        calls.append(locale)
        return render(locale)

    session = _Session(
        [("a", "organization_admin"), ("b", "organization_admin"), ("c", "organization_admin")],
        member_settings={"c": {"general.language": "de"}},
    )
    await dispatch.dispatch(session, _event(render=counting))  # type: ignore[arg-type]
    assert sorted(calls) == ["de", "en"]


# ── failing safely ───────────────────────────────────────────────────────────


async def test_an_unregistered_kind_raises_because_it_is_a_programming_error() -> None:
    """The one thing dispatch raises for. A kind nobody registered cannot be
    classified, retained or translated."""
    session = _Session([("user-1", "organization_admin")])
    with pytest.raises(KeyError):
        await dispatch.dispatch(
            session,  # type: ignore[arg-type]
            Event(
                kind="nobody.registered_this",
                tenant_id="t",
                audience=Audience(permission="settings.read"),
                render=render,
            ),
        )


async def test_a_template_that_raises_costs_that_language_and_no_other() -> None:
    def broken(locale: str) -> Rendered:
        if locale == "de":
            raise RuntimeError("the German rendering is wrong")
        return render(locale)

    session = _Session(
        [("en-person", "organization_admin"), ("de-person", "organization_admin")],
        member_settings={"de-person": {"general.language": "de"}},
    )
    outcome = await dispatch.dispatch(session, _event(render=broken))  # type: ignore[arg-type]
    assert outcome.in_app == 1
    assert [row["title"] for row in session.written] == ["title-en"]


async def test_an_audience_that_resolves_nobody_is_not_an_error() -> None:
    session = _Session([("user-1", "member")])
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome == dispatch.Dispatched()


class _Broken(_Session):
    """A session whose settings tables will not answer."""

    async def execute(self, statement: object, parameters: Any = None) -> Any:  # noqa: ANN401
        if "settings" in str(statement):
            raise RuntimeError("the settings tables are unreadable")
        return await super().execute(statement, parameters)


async def test_an_unreadable_preference_leaves_the_feed_written() -> None:
    """The feed fails **open**: the worst case is a notification somebody did
    not want, in a list they can clear."""
    session = _Broken([("user-1", "organization_admin")])
    outcome = await dispatch.dispatch(session, _event())  # type: ignore[arg-type]
    assert outcome.in_app == 1


async def test_an_unreadable_preference_holds_the_mail() -> None:
    """Mail fails **closed**, and the asymmetry is the decision. DISP-03.

    A mail sent to somebody who switched mail off cannot be recalled. A mail
    withheld because a preference could not be read costs them nothing they
    have not already got, because the feed row exists either way — holding it
    loses the second copy of a notification, not the notification.
    """
    session = _Broken([], owner="owner@acme.test")
    outcome = await dispatch.dispatch(
        session,  # type: ignore[arg-type]
        _event(session_free=Audience(include_owner=True)),
    )
    assert outcome.mail == ()
    # Distinguishable from an opt-out, because only one of the two is worth
    # anybody's attention.
    assert "owner@acme.test:email_unknown" in outcome.skipped


async def test_the_shared_scopes_are_read_once_however_many_recipients() -> None:
    """DISP-01. The platform's defaults and the organisation's values cannot
    change during one dispatch, and they were read once per person per channel:
    eleven times each for ten approvers, on the request path, while somebody
    waited for an assistant to answer.

    Asserted as a count rather than as a shape, because the defect was
    invisible to every assertion about what was decided.
    """
    counts: dict[int, dict[str, int]] = {}
    for many in (1, 10):
        session = _Counting(
            [(f"user-{n}", "organization_admin") for n in range(many)],
            owner="owner@acme.test",
        )
        await dispatch.dispatch(
            session,  # type: ignore[arg-type]
            _event(session_free=Audience(permission="settings.read", include_owner=True)),
        )
        counts[many] = session.tally()

    for table in ("global_settings", "tenant_setting_values", "tenant_members"):
        assert counts[1][table] == 1, f"{table} is read more than once for one recipient"
        assert counts[10][table] == 1, f"{table} is read once per recipient"

    # A member's own row is read once per person -- not once for their language
    # and again for each channel, which is what made it twenty for ten.
    assert counts[1]["member_setting_values"] == 1
    assert counts[10]["member_setting_values"] == 10


async def test_a_template_is_rendered_once_per_language_in_both_channels() -> None:
    """DISP-02. The feed grouped by language and the inbox did not, so a
    template doing real work did it once per recipient in the inbox half. The
    test that claimed otherwise used a case with no addresses in it."""
    calls: list[str] = []

    def counting(locale: str) -> Rendered:
        calls.append(locale)
        return render(locale)

    session = _Session(
        [("a", "organization_admin"), ("b", "organization_admin")],
        owner="owner@acme.test",
    )
    outcome = await dispatch.dispatch(
        session,  # type: ignore[arg-type]
        _event(
            session_free=Audience(permission="settings.read", include_owner=True),
            render=counting,
        ),
    )
    # Two feed rows and one mail, all in English, from one rendering.
    assert outcome.in_app == 2
    assert len(outcome.mail) == 1
    assert calls == ["en"]
