import asyncio
from arq import run_worker
from arq.connections import RedisSettings
from .worker import WorkerSettings


if __name__ == "__main__":
    asyncio.run(run_worker(WorkerSettings))  # type: ignore[arg-type]
