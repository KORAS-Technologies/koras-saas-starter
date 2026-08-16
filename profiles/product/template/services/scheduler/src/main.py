from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio


scheduler = AsyncIOScheduler()


@scheduler.scheduled_job(CronTrigger(hour=0, minute=0))
async def daily_cleanup() -> None:
    """Placeholder scheduled job — replace with real business logic."""
    pass


async def main() -> None:
    scheduler.start()
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
