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


settings = Settings()  # type: ignore[call-arg]
