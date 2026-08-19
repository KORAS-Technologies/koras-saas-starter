from koras_platform import Environment
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Required, with no default. A bare `str = "dev"` means a missing or
    # misspelled value yields a valid-looking configuration, and every
    # environment-isolation guarantee downstream rests on this being correct.
    environment: Environment

    database_url: str
    database_pool_size: int = 10

    zitadel_domain: str
    zitadel_project_id: str

    cors_origins: list[AnyHttpUrl] = []

    doppler_token: str = ""

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"


settings = Settings()  # type: ignore[call-arg]
