"""The four KORAS environments.

Every generated project -- product and control plane alike -- runs as exactly
one of these, mapped from the git branch that deployed it:

    develop -> dev    test -> test    staging -> stg    main -> prod

Environment isolation is the most consequential control in the platform. A dev
deployment reaching prod ZITADEL, Supabase, or a product API would cross the
boundary that keeps customer data separate, and the entire guarantee rests on
this one value being right. It is therefore a closed set with no default and no
fallback.
"""

from __future__ import annotations

from enum import StrEnum


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STG = "stg"
    PROD = "prod"

    @property
    def is_production(self) -> bool:
        return self is Environment.PROD


def resolve_environment(value: str | Environment | None) -> Environment:
    """Parse an environment name, refusing anything unrecognised.

    There is deliberately no default. A typo such as ``prd``, or an unset
    variable, must stop the process rather than resolve to something plausible.

    Note that falling back to ``dev`` would be no safer than falling back to
    ``prod``: it would point a production deployment at development
    infrastructure and appear to work, which is the harder failure to notice.

    Raises:
        ValueError: if the value is missing or not one of the four environments.
    """
    if value is None or value == "":
        raise ValueError(
            "No environment configured. Set ENVIRONMENT to one of: "
            + ", ".join(e.value for e in Environment)
        )
    if isinstance(value, Environment):
        return value
    try:
        return Environment(value.strip().lower())
    except ValueError:
        raise ValueError(
            f"Unknown environment {value!r}. Expected one of: "
            + ", ".join(e.value for e in Environment)
        ) from None
