from koras_platform import Environment
from pydantic import RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SweepSettings(BaseSettings):
    """Settings for a sweep, where a blank value means the setting is absent.

    A secret store is not an environment. Doppler holds a key with an empty
    value as readily as it holds no key at all, and somebody turning a sweep off
    by clearing its box is doing the obvious thing. Pydantic disagrees: `bool`
    refuses `""` outright, so a cleared switch does not read as off -- it raises
    `ValidationError` when the sweep constructs its settings, which is to say
    the job that was meant to be disabled now fails every night at 04:07.

    Found on 2026-09-17 with `STORAGE_LIFECYCLE_ENABLED` blank in dev. The
    setting whose whole purpose is to keep a deleting sweep switched off was the
    one a blank value broke.

    So a blank is dropped before validation and the field's own default applies.
    Every sweep here defaults to off or to a value that skips, so clearing a box
    does what clearing a box looks like it does.

    A field whose default is already `""` is unaffected -- dropping an empty
    value leaves it empty. A required field with no default still fails, and
    should: "this must be configured" and "this may be blank" are different
    claims, and only the first one is safe to guess.
    """

    @model_validator(mode="before")
    @classmethod
    def _blank_means_absent(cls, values: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in values.items()
            if not (isinstance(value, str) and value.strip() == "")
        }


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


settings = Settings()  # type: ignore[call-arg]
