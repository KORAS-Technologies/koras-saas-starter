from arq.connections import RedisSettings
from .tasks import example_task


class WorkerSettings:
    functions = [example_task]
    redis_settings = RedisSettings(host="localhost", port=6379)
    max_jobs = 10
    job_timeout = 300
