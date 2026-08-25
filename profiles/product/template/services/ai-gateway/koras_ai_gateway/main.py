import asyncio

import uvicorn
from litellm.proxy.proxy_server import app, initialize

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
