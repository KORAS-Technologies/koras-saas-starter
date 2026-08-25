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
    # The OIDC client id, which is the audience of an ID token. Without it the
    # API rejects every token the applications hold.
    zitadel_client_id: str | None = None

    cors_origins: list[AnyHttpUrl] = []

    # The environment's own Upstash database, holding the rate-limit counters.
    # Empty is legitimate -- locally, and in a test, there is no Redis, and the
    # limiter treats its absence as the degraded case rather than an error.
    # This schema scopes rows by tenant in its policies, so a connection that
    # bypasses RLS has none of that scoping. Checked at startup; see R-032.
    require_rls_enforcement: bool = True

    redis_url: str = ""

    # Whether X-Forwarded-For can be believed. False by default: the header is
    # set by anyone who wants to set it, and trusting it where no proxy rewrites
    # it gives a caller a fresh rate-limit quota per request. Turn it on only
    # where a CDN or load balancer is guaranteed to be in front.
    trust_forwarded_for: bool = False

    doppler_token: str = ""

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"


settings = Settings()  # type: ignore[call-arg]
