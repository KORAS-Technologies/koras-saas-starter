"""Owing a message, against a real PostgreSQL with row-level security on.

**This file exists because the outbox could never record a single message.**

`core/outbox.py` wrote its row with `insert ... returning id`. Reading a row
back needs a policy that admits it, and `notification_outbox` deliberately has
**no tenant select policy at all** -- it holds the rendered body of every
notification, including ones addressed to a colleague. So every enqueue made
from a customer's request, in every generated product, was refused with "new
row violates row-level security policy", from the day the outbox shipped until
2026-09-22.

Nothing saw it. `300_notification_outbox_isolation.sql` asserts that a tenant
*may* insert -- and it is right, and it passes, because the insert it makes has
no `returning` clause and is therefore not the insert the product made. Every
Python test that reached `enqueue` used a double or a provisioning context,
whose policy is `for all` and admits the read. The gap is exactly the
FW-HARDEN-001 shape: an assertion that asks what a contract says rather than
what the code does.

**So this test calls `enqueue` itself**, on a session bound the way a request
binds it, against policies that are on. Against a double it proves nothing: a
fake session has no policies, so the refusal cannot happen. Only a real
PostgreSQL and a role without `BYPASSRLS` reproduce it.

Skipped without a database, for the reason `playwright.config.ts` gives about
the round trip, and on the same variable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("ENVIRONMENT", "dev")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

#: The organisation `e2e/support/seed.sql` creates.
TENANT = "00000000-0000-4e2e-8000-000000000001"

#: How a request binds its caller: transaction-local, and provisioning off.
#: Written out rather than imported so that a change to the engine's own
#: declaration cannot quietly make this test bind something else.
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL, poolclass=None)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
            yield opened
    finally:
        await engine.dispose()


async def test_a_customer_request_can_owe_a_message(session: AsyncSession) -> None:
    """The whole claim: `enqueue` succeeds on a tenant-bound session.

    It returned `None` on every call before the fix, and `None` is what
    `enqueue` also returns when it is working and the row is refused -- which
    is why this asserts the row is *there* rather than that the call returned
    something.
    """
    from koras_api.core import outbox

    await session.execute(AS_TENANT, {"tenant_id": TENANT})
    message_id = await outbox.enqueue(
        session,
        tenant_id=TENANT,
        kind="ai.approval_requested",
        recipient="owner@example.test",
        locale="en",
        subject="Approval needed",
        body_text="text",
        body_html="<p>html</p>",
    )
    assert message_id is not None, "the outbox refused a message a customer request owed"
    await session.commit()

    await session.execute(AS_PROVISIONING)
    row = (
        await session.execute(
            text(
                "select recipient, status, attempts from public.notification_outbox "
                "where id = cast(:id as uuid)"
            ),
            {"id": message_id},
        )
    ).first()
    assert row is not None, "enqueue answered an id for a row that is not there"
    assert (row.recipient, row.status, row.attempts) == ("owner@example.test", "pending", 0)


async def test_a_refused_message_leaves_the_caller_s_transaction_usable(
    session: AsyncSession,
) -> None:
    """The promise `enqueue`'s docstring makes, which catching alone cannot keep.

    PostgreSQL aborts the whole transaction on an error, so swallowing the
    exception left the caller holding a transaction in which nothing further
    could be written and everything already written was lost. In `dispatch`
    that meant one refused mail silently destroyed the in-app notifications
    written moments earlier -- both channels gone, and the count said one.

    A message for *another* tenant is the refusal used here because it is the
    one a policy will always refuse.
    """
    from koras_api.core import outbox

    # Unique per run, and the assertion counts only this run's row. Both tests
    # here commit, so a fixed title would count every previous run's rows too
    # and the suite would pass exactly once -- which `e2e/support/seed.sql`
    # names as the reason a fixture has to be repeatable. Caught by running it
    # twice, which is the only way that shows.
    title = f"written before the refusal {uuid.uuid4()}"

    await session.execute(AS_TENANT, {"tenant_id": TENANT})
    await session.execute(
        text(
            "insert into public.notifications (tenant_id, user_id, kind, title, body) "
            "values (cast(:tenant_id as uuid), :user_id, :kind, :title, :body)"
        ),
        {
            "tenant_id": TENANT,
            "user_id": "e2e-subject",
            "kind": "ai.approval_requested",
            "title": title,
            "body": "body",
        },
    )

    refused = await outbox.enqueue(
        session,
        tenant_id="00000000-0000-0000-0000-0000000000ff",
        kind="ai.approval_requested",
        recipient="elsewhere@example.test",
        locale="en",
        subject="Not ours",
        body_text="text",
        body_html="<p>html</p>",
    )
    assert refused is None, "a message for another tenant was recorded"

    # The transaction still works, and the row written before the refusal is
    # still there to commit. Before the savepoint this raised instead.
    await session.commit()

    await session.execute(AS_PROVISIONING)
    kept = (
        await session.execute(
            text(
                "select count(*) as n from public.notifications "
                "where tenant_id = cast(:t as uuid) and title = :title"
            ),
            {"t": TENANT, "title": title},
        )
    ).scalar_one()
    assert kept == 1, "a refused mail took the in-app notification with it"
