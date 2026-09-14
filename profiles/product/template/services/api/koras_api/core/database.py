"""The request sessions and the startup check, for a product.

Per profile rather than shared: the two profiles differ in exactly the part
that matters here, and a `_shared` template may not also exist in a profile.
The logic both need lives in `koras_database`; this file is the wiring.

The pool itself moved to `core/engine.py` when the tenant lookup became a real
query: this module depends on a resolved tenant, resolving one needs a session,
and a module cannot import what imports it.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from koras_database import declare, verify_connection_enforces_rls
from koras_tenant import Provisioning, Tenant
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import SessionLocal
from .settings import settings
from .tenant import TenantDep


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """A session scoped to one tenant, for the request and for what outlives it.

    `get_db` is this for a request. A route that answers over time -- the
    assistant's stream -- opens one of its own here, because the request's
    session is closed on the framework's schedule and a stream outlives
    it. One place binds the tenant, so the two cannot bind it differently.
    """
    async with SessionLocal() as session:
        declare(Tenant(tenant_id=tenant_id))
        yield session


async def rebind_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Bind the tenant again after a commit, where the binding is a statement.

    The tenant setting is transaction-local and a commit ends the
    transaction; a store that commits mid-request still has rows to write
    on the same session. Here the engine re-declares the caller at the
    start of every transaction from the task's declaration, so there is
    nothing to do -- the function exists so the AI core, which runs on
    repositories with either design, has one name to call.
    """
    del session, tenant_id


async def get_db(tenant: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    """A session with this request's tenant context set.

    The context is transaction-local, so it cannot outlive the request on a
    pooled connection and be inherited by whoever gets that connection next.
    """
    async with tenant_session(tenant.id) as session:
        yield session


async def get_platform_session() -> AsyncGenerator[AsyncSession, None]:
    """A session for the private platform API, which has no tenant to scope to.

    Deliberately not `get_db` with a flag. `get_db` depends on `TenantDep`,
    which depends on a customer token and a resolved tenant -- neither of which
    exists on a call whose purpose is to create the tenant. Those dependencies
    are the point: a route that wanted both behaviours would have to make the
    tenant optional, and an optional tenant context is one that is missing on
    the path nobody tested.

    What this grants instead is stated on `Provisioning`, and it is
    broad: within this transaction the connection reads and writes every tenant
    row. That is why it is reachable from exactly one router, which admits a
    machine identity alone.
    """
    async with SessionLocal() as session:
        declare(Provisioning())
        yield session


# Aliases rather than `Depends(...)` in each signature, because the contract
# test reads the router's handler signatures and a parenthesis inside one puts
# the whole route beyond its regex -- silently, as a route it stops checking
# rather than as a failure.
#
# The two are not interchangeable and the names say so. `DbSession` is scoped to
# one tenant and is what every customer-facing route takes; `PlatformSession`
# can read and write every tenant row and is reachable from one router, which
# admits a machine identity alone.
DbSession = Annotated[AsyncSession, Depends(get_db)]
PlatformSession = Annotated[AsyncSession, Depends(get_platform_session)]


async def verify_rls_enforcement() -> None:
    """Called from the lifespan, before anything is served."""
    await verify_connection_enforces_rls(SessionLocal, required=settings.require_rls_enforcement)
