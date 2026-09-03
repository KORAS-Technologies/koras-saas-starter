from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Protocol

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class UndeclaredCaller(RuntimeError):
    """A transaction was opened without saying who it is for.

    Raised rather than allowed to proceed. An undeclared caller sees zero rows,
    and zero rows is indistinguishable from a customer who genuinely has none --
    which is how a policy set comes to be inert for months without anybody
    noticing. A missing declaration is a programming error and should look like
    one.
    """


class Declaration(Protocol):
    """Who a transaction is for, in whichever vocabulary the schema uses.

    The seam between what is shared and what is not. The guard, the event, the
    context variable and the refusal are the same for every profile; the
    settings are not. A product scopes rows by tenant; the Control Plane scopes
    them by actor and organization. Neither vocabulary belongs in this package.
    """

    def settings(self) -> Mapping[str, str]:
        """The transaction-local settings this declaration sets.

        Bound as parameters, never interpolated: `SET` takes no bind parameters,
        so a `SET LOCAL` here would mean building a statement out of a value
        that arrived in a token -- an injection vector in the one function the
        whole tenant boundary depends on.
        """
        ...


_current: ContextVar[Declaration | None] = ContextVar("koras_rls_declaration", default=None)


@contextmanager
def acting_as(declaration: Declaration) -> Iterator[None]:
    """Declare, for everything done inside this block."""
    token = _current.set(declaration)
    try:
        yield
    finally:
        _current.reset(token)


def declare(declaration: Declaration) -> None:
    """Declare, for the rest of this task.

    The scoped `acting_as` cannot be combined with `async with` in one
    statement -- a synchronous context manager and an asynchronous one do not
    mix -- and wrapping a whole request body in an extra block to satisfy that
    is indentation in service of syntax.

    Safe because a context variable set inside an asyncio Task is confined to
    it: each request and each background job runs as its own Task with its own
    copied context, so one cannot observe another's declaration, and there is
    nothing to reset because the context ends with the task.

    Use `acting_as` where the caller changes part-way through a scope; use this
    where a whole task has one.
    """
    _current.set(declaration)


def current_declaration() -> Declaration | None:
    return _current.get()


def install_rls(engine: AsyncEngine) -> None:
    """Refuse to open a transaction that has not said who it is for.

    This replaces a pair of helpers a caller had to remember to call, and the
    direction the two designs fail in is the whole argument. A missed call
    yields a query that succeeds and returns **more** than it should, which
    looks exactly like a working feature. A missed declaration refuses to open
    the transaction. Only one of those is survivable.

    Not hypothetical: a helper of that shape shipped, nothing ever called it,
    the services connected as the table owner so RLS never applied, and the
    policies sat inert while everyone believed they were load bearing. It was
    found by connecting as the restricted role and counting rows, not by
    anything failing.

    On the **engine** rather than a session class, because the engine is the
    narrower waist: it covers sessions built directly, connections taken outside
    a session, and anything added later, none of which a session-level listener
    would see.

    On `begin` rather than once per session, because the settings are
    transaction-local and repositories commit part-way through their work. After
    a commit SQLAlchemy opens a new transaction, and a context established at
    session open is gone for every statement following the first commit.
    `begin` fires for each of them.
    """

    @event.listens_for(engine.sync_engine, "begin")
    def _declare(connection: Connection) -> None:
        declaration = _current.get()
        if declaration is None:
            raise UndeclaredCaller(
                "A database transaction was opened without declaring who it is "
                "for. Wrap the work in koras_database.acting_as(...), or "
                "declare(...) for a whole task."
            )

        settings = declaration.settings()
        if not settings:
            # Not an error. A declaration that sets nothing says "this
            # transaction reads nothing a policy scopes" -- see
            # `SystemTransaction` -- and that is a statement rather than an
            # omission. The failure this guard exists to catch is the absence of
            # any declaration at all, which is the branch above.
            return

        # One statement, bound. Built from the declaration's own keys rather
        # than from a fixed list, which is what lets a profile carry its own
        # vocabulary without this function knowing it.
        bound = {_bind(name): value for name, value in settings.items()}
        assignments = []
        for name in settings:
            parameter = _bind(name)
            assignments.append(f"set_config('{name}', :{parameter}, true)")

        connection.execute(text("select " + ", ".join(assignments)), bound)


def _bind(setting_name: str) -> str:
    """A bind-parameter name for a setting name.

    `app.tenant_id` is not a legal parameter name, and the setting names are
    ours rather than a caller's -- so this maps rather than validates.
    """
    return setting_name.replace(".", "_")


@dataclass(frozen=True)
class SystemTransaction:
    """Work that no policy scopes, declared as such.

    The startup check reads `pg_roles` to find out whether this connection can
    be restrained by row-level security at all. There is no tenant, no
    organization and no actor involved, and no policy applies to the row it
    reads.

    It still declares. Under `install_rls` the alternative is not "runs without
    context" but "refuses to open", and a service that cannot complete its own
    startup check is a service that will not start. Naming the case is also the
    point: an exemption that has to be written down is one a reader can find,
    where a special case inside the guard would not be.
    """

    def settings(self) -> Mapping[str, str]:
        return {}


class RlsNotEnforced(RuntimeError):
    """The connection bypasses row-level security, so policies do nothing."""


async def assert_rls_enforced(session: AsyncSession) -> None:
    """Refuse to serve on a connection that row-level security cannot restrain.

    `alter table ... force row level security` subjects the table's *owner* to
    its policies. It does not subject a **superuser**, and it does not subject a
    role holding BYPASSRLS -- those bypass RLS unconditionally, forced or not.

    That distinction is invisible until it is measured, and measuring it was the
    only way it was found. Against a real database:

        connecting role        force   rows visible
        superuser              ON      2   <- bypassed
        non-superuser owner    ON      1   <- isolated
        non-superuser owner    OFF     2   <- bypassed

    A managed Postgres commonly hands out a superuser as the default connection
    role, and a DATABASE_URL copied from a dashboard is usually that role. Such
    a deployment has correct policies, `force` set on every table, a passing
    policy test suite, and no row-level security whatsoever.

    So the check is made at startup, once, where it is loud. The alternative is
    discovering it from a customer who has seen another tenant's data.
    """
    result = await session.execute(
        text(
            "select current_user, "
            "coalesce(rolsuper, false), coalesce(rolbypassrls, false) "
            "from pg_roles where rolname = current_user"
        )
    )
    row = result.first()
    if row is None:  # pragma: no cover - current_user always has a pg_roles row
        return

    user, is_superuser, bypasses_rls = row
    if is_superuser or bypasses_rls:
        reason = "a superuser" if is_superuser else "granted BYPASSRLS"
        raise RlsNotEnforced(
            f"The database connection uses {user!r}, which is {reason}. "
            "Row-level security is bypassed on this connection, so every tenant "
            "policy is inert and queries can return other tenants' rows. "
            "Connect as a role that is neither, and grant it only the table "
            "privileges the service needs."
        )


async def verify_connection_enforces_rls(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    required: bool,
) -> None:
    """Startup check, for the profiles whose policies do the scoping.

    Lives here rather than in each service's `core/database.py` because both
    profiles need it and neither may hold the shared copy: `_shared` templates
    are single-sourced, and a path there may not also exist in a profile. A
    package is where logic two profiles share actually belongs.

    `required` is the profile's answer to whether its policies do the scoping.
    A product's do, so a connection that bypasses RLS has none of it. The
    Control Plane has no policies at all -- its tables carry RLS as a
    deny-by-default backstop and the service role is meant to bypass -- so
    asserting the product's rule there would refuse to start a service working
    exactly as designed.
    """
    if not required:
        return

    # Declared here rather than by every caller: this function owns the
    # transaction it opens, and a startup check that made each service remember
    # to wrap it would be the kind of call people forget -- which is the shape
    # `install_rls` exists to make impossible.
    with acting_as(SystemTransaction()):
        async with session_factory() as session:
            await assert_rls_enforced(session)
