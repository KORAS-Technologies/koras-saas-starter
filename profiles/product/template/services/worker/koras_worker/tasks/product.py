"""This product's own scheduled work.

The extension point. The starter ships the sweeps every product needs — audit
retention, the governance expiries, the storage lifecycle, reconciliation,
backup and restore — and nothing of any product's domain. A product adds its
own here, and `worker.py` picks them up with no other change.

**Why this file exists at all.** It did not until 2026-09-16, and its absence
had already cost something: `koras-e2e-shop` wrote a retention sweep for its
own orders, tested it, and never scheduled it. `worker.py` is generated and a
product that edited it would carry a permanent conflict into every future sync,
so the sweep had nowhere to register. It was dead code with a passing test —
the test imported the function directly and asserted nothing about it running.
A seam is what stops the next product making the same trade.

A cron job is arq's `cron(coroutine, ...)`. The coroutine takes the worker
context and returns whatever it likes; nothing reads the return value but the
log.

    from arq import cron
    from arq.cron import CronJob

    from .shop import purge_shop_orders

    PRODUCT_CRON_JOBS: list[CronJob] = [
        # Nightly, at an hour nothing else uses. The starter's own sweeps sit
        # between 03:17 and 04:39, so a product's work goes outside that.
        cron(purge_shop_orders, hour=5, minute=11),
    ]

Two things worth keeping in mind when adding one.

**Pick an hour the starter is not using.** Its sweeps run between 03:17 and
04:39 and more may arrive. A product's job at 04:07 would compete with the
storage lifecycle for the same connection pool on the same night.

**A sweep that deletes should be off until something asks for it.** Every
destructive sweep the starter ships reads a setting first and skips loudly when
it is unset, so a product cannot acquire a deletion by upgrading. The same
applies here and nothing enforces it.
"""

from __future__ import annotations

from arq.cron import CronJob
from koras_queue import BoundTask

#: Read by `worker.py` and extended onto the starter's own list. Empty here,
#: because the starter has no product domain; a generated project fills it in.
PRODUCT_CRON_JOBS: list[CronJob] = []

#: This product's own on-demand work: jobs a request asks for, rather than jobs
#: a clock starts.
#:
#: The second half of this extension point, added on 2026-09-19. Until then
#: `PRODUCT_CRON_JOBS` was the whole of it and it took cron jobs only, so a
#: product that needed something done *when something happened* had two
#: choices: edit `worker.py`, which is generated and reverts on the next sync,
#: or add a cron job that polls a table every minute for things to do. Docoris
#: recorded that as its OD-19 rather than writing the workaround.
#:
#: A `BoundTask` is a declaration and the coroutine that answers it::
#:
#:     from koras_api.jobs import REBUILD_INDEX
#:     from koras_queue import BoundTask
#:
#:     from .search import rebuild_index
#:
#:     PRODUCT_TASKS: list[BoundTask] = [BoundTask(REBUILD_INDEX, rebuild_index)]
#:
#: **Declare the `TaskDefinition` where the API can import it**, not here. The
#: API is what enqueues, and an API that imported the worker to find a task
#: name would point the dependency arrow from a request at a sweep.
#:
#: Two things about the handler, both of which have teeth:
#:
#: **It declares its own tenant.** The envelope carries one and the enqueue
#: refuses a blank, but nothing opens a transaction for you -- a handler that
#: forgets `Tenant(...)` raises `UndeclaredCaller` rather than reading across
#: tenants, which is the right failure and still a failure.
#:
#: **It is retried, so it must be safe to run twice.** The declared policy
#: decides how often; at-least-once is the guarantee either way. A handler that
#: is not idempotent needs `TRY_ONCE` and a visible failure instead.
PRODUCT_TASKS: list[BoundTask] = []
