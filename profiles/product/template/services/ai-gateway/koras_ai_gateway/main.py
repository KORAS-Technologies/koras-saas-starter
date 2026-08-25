import uvicorn
from litellm.proxy.proxy_server import app, initialize

if __name__ == "__main__":
    initialize(config="./litellm_config.yaml")
    # Binds every interface deliberately. This runs as the only process in a
    # container, where 127.0.0.1 would make it unreachable from outside that
    # container -- including from its own healthcheck. Exposure is decided by
    # the network the container joins, not by this line.
    uvicorn.run(app, host="0.0.0.0", port=4000)  # noqa: S104
