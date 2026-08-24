from arq.connections import RedisSettings

from .settings import settings
from .tasks import example_task


class WorkerSettings:
    functions = [example_task]
    # Derived from REDIS_URL rather than hardcoded. A fixed localhost:6379 is
    # not merely wrong once deployed -- the worker starts, stays up, and quietly
    # consumes an empty local queue while the real one fills elsewhere. On a
    # developer machine running more than one KORAS stack it connects to
    # whichever project happens to hold 6379.
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    # arq polls every 0.5s by default: two Redis commands a second per worker,
    # forever, whether or not there is work. On a per-command managed queue that
    # is ~170,000 commands a day on an idle platform, and enough to exhaust a
    # free tier within minutes of starting.
    #
    # Nothing here needs sub-second pickup, so five seconds costs nothing
    # perceptible and removes ninety per cent of the idle traffic.
    poll_delay = 5.0
    max_jobs = 10
    job_timeout = 300
