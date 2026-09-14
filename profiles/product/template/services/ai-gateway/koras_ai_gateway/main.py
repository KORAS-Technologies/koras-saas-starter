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

import asyncio  # noqa: E402

import uvicorn  # noqa: E402
from litellm.proxy.proxy_server import app, initialize  # noqa: E402

from .guard import RequireBearer  # noqa: E402

# In front of the proxy, so a request with no key is a 401 here and never
# reaches the handler that turns it into a 500. See guard.py.
app.add_middleware(RequireBearer)

if __name__ == "__main__":
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
    asyncio.run(initialize(config="./litellm_config.yaml"))  # type: ignore[no-untyped-call]
    # Binds every interface deliberately. This runs as the only process in a
    # container, where 127.0.0.1 would make it unreachable from outside that
    # container -- including from its own healthcheck. Exposure is decided by
    # the network the container joins, not by this line.
    uvicorn.run(app, host="0.0.0.0", port=4000)  # noqa: S104
