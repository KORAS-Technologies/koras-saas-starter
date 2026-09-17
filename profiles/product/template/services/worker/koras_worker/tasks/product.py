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

#: Read by `worker.py` and extended onto the starter's own list. Empty here,
#: because the starter has no product domain; a generated project fills it in.
PRODUCT_CRON_JOBS: list[CronJob] = []
