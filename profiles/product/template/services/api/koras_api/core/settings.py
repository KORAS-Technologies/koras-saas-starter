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
    # Which machine identity may call the private platform API.
    #
    # The `sub` of the estate's `product-caller` service account. An identifier
    # rather than a credential: it authorises nothing on its own, and knowing it
    # gets a caller no closer to minting a token ZITADEL will sign.
    #
    # Empty is allowed here so the service still starts -- health, and every
    # customer-facing route, are unaffected by it. It is *not* allowed at the
    # gate: `require_platform_machine` refuses while it is unset rather than
    # falling back to admitting any machine account. See platform_auth.py.
    zitadel_platform_caller_sub: str = ""

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

        Not hypothetical. This is what the first deployment of a generated
        product did, on 2026-08-30: the image built and pushed, the machine
        launched, nothing ever bound to 0.0.0.0:8000, and Fly reported only
        that the app was not listening on the expected address. The cause was
        eleven frames down a traceback in the machine's own logs.
        """
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value


settings = Settings()  # type: ignore[call-arg]
