import os

# Before importing litellm. The deploy injects the whole product's Doppler
# environment into every service, so this container receives DATABASE_URL --
# the restricted role the API and worker connect as. LiteLLM turns on its own
# Prisma-backed key store the instant it sees that variable and then dies at
# startup with `ModuleNotFoundError: No module named 'prisma'`, because this is
# deliberately a keyless proxy with no database of its own (see
# litellm_config.yaml). The machine restart-loops and never becomes healthy, so
# the deploy times out. The gateway has no database, so the variable is not
# meant for it: drop it before litellm can read it. Same for a Redis URL, which
# LiteLLM would otherwise adopt as a cache backend nobody configured.
for _leaked in ("DATABASE_URL", "DATABASE_ADMIN_URL", "REDIS_URL"):
    os.environ.pop(_leaked, None)

import argparse  # noqa: E402
import asyncio  # noqa: E402

import uvicorn  # noqa: E402
from litellm.proxy.proxy_server import app, initialize  # noqa: E402

from .guard import RequireBearer  # noqa: E402

# In front of the proxy, so a request with no key -- or the wrong one, where
# the master key is configured -- is a 401 here and never reaches the handler
# that turns it into a 500. See guard.py.
app.add_middleware(RequireBearer, key=os.environ.get("LITELLM_MASTER_KEY"))


def main(argv: list[str] | None = None) -> None:
    """Load the configuration, then serve.

    The one way to start this service, in the container and on a developer
    machine alike. `make dev` used to start it through uvicorn's import path,
    which loads this module and never calls `initialize`, so the proxy served
    with no models loaded while looking configured; it now runs this.
    """
    parser = argparse.ArgumentParser(prog="koras_ai_gateway")
    # Binds every interface by default, deliberately. In the container this is
    # the only process, and 127.0.0.1 would make it unreachable from outside
    # -- including from its own healthcheck. Exposure is decided by the
    # network the container joins. A developer machine passes 127.0.0.1.
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument(
        "--config", default=os.environ.get("LITELLM_CONFIG", "./litellm_config.yaml")
    )
    args = parser.parse_args(argv)

    # `initialize` is a coroutine. Called without awaiting it, the coroutine is
    # created, discarded, and never runs -- so litellm_config.yaml is never
    # read and the proxy serves with default settings while appearing to be
    # configured. Nothing surfaced it: the AI gateway is an optional component
    # and no run generated one, so the service was never typechecked or started.
    #
    # `type: ignore[no-untyped-call]`: litellm ships py.typed but annotates
    # neither this function's parameters nor its return, so mypy sees an
    # untyped call in a typed context. The ignore is at the call rather than
    # over the module, which would hide the same mistake in every other litellm
    # call this file might grow.
    asyncio.run(initialize(config=args.config))  # type: ignore[no-untyped-call]
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
