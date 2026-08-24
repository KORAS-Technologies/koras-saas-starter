import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# APScheduler ships no type information for `scheduled_job`, so mypy sees an
# untyped decorator and treats everything it wraps as untyped too -- which
# silently switches off checking inside the job bodies, the one place a
# scheduler's mistakes are expensive. Ignored at each use rather than by
# relaxing the setting for the module.


@scheduler.scheduled_job(CronTrigger(minute="*/15"))  # type: ignore[untyped-decorator]
async def reconciliation_sweep() -> None:
    """Trigger periodic infrastructure reconciliation for all registered products."""
    pass


@scheduler.scheduled_job(CronTrigger(hour=1, minute=0))  # type: ignore[untyped-decorator]
async def subscription_renewal_check() -> None:
    """Check subscriptions due for renewal and enqueue billing tasks."""
    pass


async def main() -> None:
    scheduler.start()
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
