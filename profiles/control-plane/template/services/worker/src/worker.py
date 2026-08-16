from arq.connections import RedisSettings
from .tasks import provision_product, reconcile_infrastructure


class WorkerSettings:
    functions = [provision_product, reconcile_infrastructure]
    redis_settings = RedisSettings(host="localhost", port=6379)
    max_jobs = 5
    job_timeout = 600
