import uvicorn
from litellm.proxy.proxy_server import app, initialize

if __name__ == "__main__":
    initialize(config="./litellm_config.yaml")
    uvicorn.run(app, host="0.0.0.0", port=4000)
