"""Which gateway model answers each alias, by default.

The product's own catalogue: for each alias product code may name, the routes
that can serve it in preference order. Every `model` here is a `model_name`
from `services/ai-gateway/litellm_config.yaml` and nothing else -- the gateway
is where a name becomes a vendor call, and the starter's structural test
keeps this file and that one level.

The Control Plane's routing policy, where a customer has one, chooses the
providers and may name the primary model; this catalogue supplies whatever
the policy leaves out. Change a default here and every customer without a
policy follows; change it there and one customer does.
"""

from __future__ import annotations

from koras_ai import ModelAlias, ModelCatalogue, ModelRoute

#: The provider names, in the platform's vocabulary, that the gateway serves.
#: A customer's policy may name others -- a private model of their own -- and
#: those are skipped until a provider is registered for them.
PROVIDER_NAMES: tuple[str, ...] = ("openai", "anthropic", "gemini", "openrouter")

CATALOGUE = ModelCatalogue(
    {
        ModelAlias.FAST: [
            ModelRoute(provider="openai", model="gpt-4o-mini"),
            ModelRoute(provider="anthropic", model="claude-3-5-haiku"),
            ModelRoute(provider="gemini", model="gemini-2.5-flash"),
            ModelRoute(provider="openrouter", model="openrouter-llama-3.3-70b"),
        ],
        ModelAlias.BALANCED: [
            ModelRoute(provider="openai", model="gpt-4o"),
            ModelRoute(provider="anthropic", model="claude-3-5-sonnet"),
            ModelRoute(provider="gemini", model="gemini-2.5-pro"),
            ModelRoute(provider="openrouter", model="openrouter-llama-3.3-70b"),
        ],
        ModelAlias.REASONING: [
            ModelRoute(provider="anthropic", model="claude-3-5-sonnet"),
            ModelRoute(provider="openai", model="gpt-4o"),
            ModelRoute(provider="gemini", model="gemini-2.5-pro"),
            ModelRoute(provider="openrouter", model="openrouter-deepseek-r1"),
        ],
        ModelAlias.VISION: [
            ModelRoute(provider="openai", model="gpt-4o"),
            ModelRoute(provider="anthropic", model="claude-3-5-sonnet"),
            ModelRoute(provider="gemini", model="gemini-2.5-pro"),
        ],
        ModelAlias.EMBEDDING: [
            ModelRoute(provider="openai", model="text-embedding-3-small"),
            ModelRoute(provider="gemini", model="gemini-embedding"),
        ],
    }
)
