from koras_platform import Environment
from pydantic import RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker configuration, read from the environment.

    `environment` has no default: a missing or misspelled value must fail at
    startup rather than silently selecting one.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: Environment

    # Required, and deliberately not defaulted to localhost. A default here is
    # not a convenience -- it is a worker that starts, reports healthy, and
    # consumes an empty queue forever while the real one fills up somewhere
    # else.
    redis_url: RedisDsn

    #: The product's database, for sweeps that run across every tenant on the
    #: provisioning context. Empty when the worker has none, and each sweep
    #: that needs it says so and skips rather than failing the worker.
    database_url: str = ""

    #: Days an assistant conversation is kept after it was last touched before
    #: the nightly sweep removes it, messages and actions with it.
    ai_retention_days: int = 90


settings = Settings()  # type: ignore[call-arg]
