"""Aliases resolve to routes, and a silent platform is a refusal only when there is one."""

from __future__ import annotations

import pytest
from koras_ai import (
    AIConfiguration,
    AIError,
    AliasPolicy,
    ErrorCode,
    Limits,
    ModelAlias,
    ModelCatalogue,
    ModelRoute,
    StaticRouting,
    is_alias,
)


def test_the_aliases_are_a_closed_set() -> None:
    assert is_alias("koras-fast")
    assert is_alias(ModelAlias.EMBEDDING)
    assert not is_alias("gpt-4o")
    with pytest.raises(AIError) as refused:
        ModelCatalogue({"gpt-4o": [ModelRoute("openai", "gpt-4o")]})
    assert refused.value.code is ErrorCode.INVALID_MODEL_ALIAS


def test_no_policy_answers_the_catalogue_in_order(catalogue: ModelCatalogue) -> None:
    routes = catalogue.resolve(ModelAlias.FAST)
    assert [r.provider for r in routes] == ["openai", "anthropic"]


def test_a_policy_reorders_and_may_name_the_primary_model(catalogue: ModelCatalogue) -> None:
    routes = catalogue.resolve(ModelAlias.FAST, ["anthropic", "openai"], model="claude-private")
    assert routes == (ModelRoute("anthropic", "claude-private"), ModelRoute("openai", "gpt-mini"))


def test_a_policy_may_name_the_fallback_model_and_it_binds_to_the_fallback(
    catalogue: ModelCatalogue,
) -> None:
    routes = catalogue.resolve(
        ModelAlias.FAST,
        ["openai", "anthropic"],
        model="gpt-private",
        fallback_model="claude-private",
    )
    assert routes == (
        ModelRoute("openai", "gpt-private"),
        ModelRoute("anthropic", "claude-private"),
    )


def test_a_fallback_model_for_a_provider_the_catalogue_lacks_goes_with_it(
    catalogue: ModelCatalogue,
) -> None:
    # The model was named for the skipped provider; it must not land on the
    # next one, which would send a Gemini model name to OpenAI.
    routes = catalogue.resolve(
        ModelAlias.FAST, ["anthropic", "private-llama", "openai"], fallback_model="llama-70b"
    )
    assert routes == (ModelRoute("anthropic", "claude-mini"), ModelRoute("openai", "gpt-mini"))


def test_a_policy_naming_only_unknown_providers_is_a_configuration_error(
    catalogue: ModelCatalogue,
) -> None:
    # Never a fall-through to the default: the customer chose a provider the
    # product cannot serve, and serving another is the decision they refused.
    with pytest.raises(AIError) as refused:
        catalogue.resolve(ModelAlias.FAST, ["private-llama"])
    assert refused.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "private-llama" not in refused.value.message


def test_an_alias_with_no_route_is_a_configuration_error(catalogue: ModelCatalogue) -> None:
    with pytest.raises(AIError) as refused:
        catalogue.routes_for(ModelAlias.VISION)
    assert refused.value.code is ErrorCode.CONFIGURATION_ERROR


class _Silent:
    async def policy_for(self, alias: str) -> AliasPolicy | None:
        return None


class _Routing:
    async def policy_for(self, alias: str) -> AliasPolicy | None:
        return AliasPolicy(providers=("anthropic",))


async def test_with_no_platform_the_catalogue_decides(catalogue: ModelCatalogue) -> None:
    configuration = AIConfiguration(catalogue=catalogue, routing=StaticRouting(), fail_closed=False)
    assert (await configuration.routes_for(ModelAlias.BALANCED))[0].provider == "openai"


async def test_with_a_platform_its_silence_is_a_refusal(catalogue: ModelCatalogue) -> None:
    configuration = AIConfiguration(catalogue=catalogue, routing=_Silent(), fail_closed=True)
    with pytest.raises(AIError) as refused:
        await configuration.routes_for(ModelAlias.BALANCED)
    assert refused.value.code is ErrorCode.CONFIGURATION_ERROR


async def test_a_platform_policy_wins_over_the_catalogue(catalogue: ModelCatalogue) -> None:
    configuration = AIConfiguration(catalogue=catalogue, routing=_Routing(), fail_closed=True)
    assert [r.provider for r in await configuration.routes_for(ModelAlias.BALANCED)] == [
        "anthropic"
    ]


def test_limits_default_to_no_ceiling_and_tools_on() -> None:
    assert Limits().monthly_requests is None
    assert Limits().tools_enabled is True
