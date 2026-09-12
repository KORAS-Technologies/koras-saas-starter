# AI gateway

A LiteLLM proxy in front of the model providers. It is an optional component:
a product only has it when generated with `--with ai_gateway`.

## What it is

An OpenAI-compatible HTTP proxy. A product does not hold provider keys or talk
to OpenAI or Anthropic directly; it calls this service, which holds the keys and
forwards the request. One place to rotate a key, one place to add a model, and
the product code stays provider-agnostic.

- Deployed as its own Fly app per environment. Its URL arrives as
  `AI_GATEWAY_URL` (derived from Terraform).
- Authenticated with `LITELLM_MASTER_KEY`, which the product sends as the
  bearer token. Without it the proxy is open to anyone who can reach it.
- The models it can reach are in `litellm_config.yaml`; the keys are read from
  the environment and declared in `local/config/secrets.manifest`.

## Configuring it

- **Add a model:** add an entry to `model_list` in `litellm_config.yaml`
  (`model_name` is what callers ask for, `litellm_params.model` is the provider
  route, `api_key` names the environment variable), then declare that variable
  in `local/config/secrets.manifest` so a deployed gateway is required to have
  it.
- **Set the keys:** locally in `.env.local`; in a deployed environment in that
  product's Doppler config (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `LITELLM_MASTER_KEY`).

## Using it from the product

The gateway speaks the OpenAI API, so any OpenAI client works — point its base
URL at `AI_GATEWAY_URL` and its key at `LITELLM_MASTER_KEY`:

```ts
import OpenAI from 'openai'

const ai = new OpenAI({
  baseURL: process.env.AI_GATEWAY_URL, // e.g. https://…-ai_gateway-dev.fly.dev
  apiKey: process.env.LITELLM_MASTER_KEY,
})

const reply = await ai.chat.completions.create({
  model: 'claude-3-5-sonnet', // a model_name from litellm_config.yaml
  messages: [{ role: 'user', content: 'Summarise this ticket…' }],
})
```

## Health

`/health/liveliness` says the process is up without calling any provider — this
is what the Fly health check and the local `health.sh` use. `/health` exists
too, but it pings every configured model on each call, so it costs money and
fails on a bad key; do not wire an automated check to it.

## What is deliberately off

- **Per-customer routing.** The Control Plane records a routing table per
  organization and capability (`ai_policies`), but this proxy routes by its
  static `model_list` and does not read that table yet. Routing is one catalog
  for all customers until that integration is built.
- **Spend tracking and virtual keys.** LiteLLM's `database_url` feature is off;
  it needs a Postgres and a migration the estate does not run.
- **Request tracing.** The langfuse callback is not configured; it needs the
  dependency and `LANGFUSE_*` secrets.
