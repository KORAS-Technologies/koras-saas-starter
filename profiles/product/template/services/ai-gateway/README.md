# AI gateway

A LiteLLM proxy in front of the model providers. It is an optional component:
a product only has it when generated with `--with ai_gateway`, and the `ai`
capability -- the assistant, the runtime and its routes -- requires it.

## What it is

An OpenAI-compatible HTTP proxy. A product does not hold provider keys or talk
to OpenAI or Anthropic directly; it calls this service, which holds the keys and
forwards the request. One place to rotate a key, one place to add a model, and
the product code stays provider-agnostic.

- Deployed as its own Fly app per environment. Its URL arrives as
  `AI_GATEWAY_URL` (derived from Terraform).
- Authenticated with `LITELLM_MASTER_KEY`, which the product's API sends as the
  bearer token. Without it the proxy is open to anyone who can reach it.
- The models it can reach are in `litellm_config.yaml`; the keys are read from
  the environment and declared in `local/config/secrets.manifest`.

## Configuring it

- **Add a model:** add an entry to `model_list` in `litellm_config.yaml`
  (`model_name` is what callers ask for, `litellm_params.model` is the provider
  route, `api_key` names the environment variable), then declare that variable
  in `local/config/secrets.manifest` so a deployed gateway is required to have
  it. If the product's catalogue should route an alias to it, add the route in
  `services/api/koras_api/ai/models.py`; the starter's structural test keeps
  the two files level.
- **Set the keys:** locally in `.env.local`; in a deployed environment in that
  product's Doppler config (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `LITELLM_MASTER_KEY`; and `GEMINI_API_KEY`, `OPENROUTER_API_KEY` when a
  customer's routing names those providers -- both optional, and a route to
  an unkeyed provider is answered with that provider's refusal rather than
  another provider's model).

## Using it from the product

Not directly. Application code never calls this service, holds its master key
or names one of its models: the `koras_ai` runtime does, from the API, under a
model alias, after the caller's tenant, permission and plan have been checked
and with a usage row written per call. A product's agents, tools and prompts
are declared in `services/api/koras_api/ai/`, and that is where a feature that
needs a model goes. See `docs/AI_DEVELOPER_GUIDE.md` in the starter.

The one thing that reaches this service from the product is the runtime's
`GatewayProvider`, speaking the OpenAI-compatible protocol with the master key
as its bearer. Anything else calling it is a design that has bypassed the
tenant boundary, the entitlement gate and the meter, and is refused in review.

## Health

`/health/liveliness` says the process is up without calling any provider -- this
is what the Fly health check and the local `health.sh` use. `/health` exists
too, but it pings every configured model on each call, so it costs money and
fails on a bad key; do not wire an automated check to it.

## What is deliberately off

- **Per-customer routing in the proxy.** The Control Plane records a routing
  policy per organization and alias, and the product's runtime reads it and
  chooses which of these models to ask for. The proxy itself routes by its
  static `model_list` and reads no policy; it does not need to, because the
  runtime has already chosen.
- **Spend tracking and virtual keys.** LiteLLM's `database_url` feature is off;
  it needs a Postgres and a migration the estate does not run. Usage is
  metered by the runtime instead, in the product's own database, per tenant.
- **Request tracing.** The langfuse callback is not configured; it needs the
  dependency and `LANGFUSE_*` secrets.

## Refusals

A request with no bearer, or with a bearer that is not `LITELLM_MASTER_KEY`,
is answered 401 by the guard in `koras_ai_gateway/guard.py` before the proxy
sees it. LiteLLM's own answer to either would be a 500, because its error
path imports the key store this image does not ship. The health endpoints
need no key.

## Starting it

`python -m koras_ai_gateway.main [--host] [--port] [--config]` is the one
entry point, in the container and under `make dev`. It loads
`litellm_config.yaml` before serving; starting the module through uvicorn's
import path skips that and serves no models.
