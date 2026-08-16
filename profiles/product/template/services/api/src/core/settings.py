from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: str = "dev"

    database_url: str
    database_pool_size: int = 10

    zitadel_domain: str
    zitadel_project_id: str

    cors_origins: list[AnyHttpUrl] = []

    doppler_token: str = ""

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"


settings = Settings()  # type: ignore[call-arg]
