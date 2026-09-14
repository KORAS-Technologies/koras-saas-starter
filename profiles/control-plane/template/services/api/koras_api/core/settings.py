from koras_platform import Environment
from pydantic import AnyHttpUrl, field_validator
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
    # False, and deliberately. The Control Plane has no tenant model and no
    # policies: its tables carry RLS as a deny-by-default backstop and the
    # service role is meant to bypass it. Asserting the product profile's rule
    # here refuses to start a service that is working as designed. See R-032.
    require_rls_enforcement: bool = False

    redis_url: str = ""

    # Whether X-Forwarded-For can be believed. False by default: the header is
    # set by anyone who wants to set it, and trusting it where no proxy rewrites
    # it gives a caller a fresh rate-limit quota per request. Turn it on only
    # where a CDN or load balancer is guaranteed to be in front.
    trust_forwarded_for: bool = False

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    #: "grpc" for the local collector, "http/protobuf" for a hosted gateway
    #: such as Grafana Cloud. Chosen in code; see core/observability.py.
    otel_exporter_otlp_protocol: str = "grpc"


    @field_validator("database_url", mode="after")
    @classmethod
    def _use_the_async_driver(cls, value: str) -> str:
        """Point the URL at asyncpg.

        Everything that hands us a connection string -- Doppler, the local
        bootstrap, psql, Supabase -- writes the driverless ``postgresql://``
        form. SQLAlchemy maps that to psycopg2, which is synchronous and is not
        a dependency of this service, so ``create_async_engine`` fails at import
        with a bare ModuleNotFoundError that says nothing about the actual
        problem. Normalising here keeps the driver an implementation detail
        rather than something every caller and every environment has to
        remember.

        The running Control Plane has carried this since it was first deployed;
        neither template did, so it was rediscovered on 2026-08-30 by the first
        deployment of a generated product. The image built, the machine
        launched, nothing bound to 0.0.0.0:8000, and Fly reported only that the
        app was not listening -- the cause was eleven frames down a traceback in
        the machine's own logs.
        """
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value


settings = Settings()  # type: ignore[call-arg]
