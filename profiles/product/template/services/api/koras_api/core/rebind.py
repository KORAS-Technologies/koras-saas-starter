"""Binding the tenant again after a commit, as a name with nothing behind it.

Its own module, and the reason is the worker. The audit sink commits and then
calls this, and the worker reaches the audit sink by name to witness an import
(ADR 0012 D5). While the function lived in `core/database.py` the sink
imported it there at the point of use -- and `core/database.py` is the
request's sessions: it imports FastAPI, the engine and the API's `Settings()`,
none of which a worker has or should have. The worker image never carried it.
So in a deployed worker every audit row an import wrote was followed by a
`ModuleNotFoundError`: the dry run's job was recorded as failed after its run
had been committed `validated`, and every commit logged that it could not be
witnessed after it had been. IMPORT-DEF-020, found on 2026-10-02 by running
the product's own image rather than its source tree.

A module that imports nothing of the API is one the worker image can carry
whole, and `tests/unit/test_worker_image_contents.py` holds the image to
carrying every module the worker reaches.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def rebind_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Bind the tenant again after a commit, where the binding is a statement.

    The tenant setting is transaction-local and a commit ends the
    transaction; a store that commits mid-request still has rows to write
    on the same session. Here the engine re-declares the caller at the
    start of every transaction from the task's declaration, so there is
    nothing to do -- the function exists so the AI core, which runs on
    repositories with either design, has one name to call.

    A worker's session has no such engine behind it. A worker that goes on
    using a session after the sink has committed binds its tenant again
    itself, which `koras_worker/tasks/imports.py` does.
    """
    del session, tenant_id
