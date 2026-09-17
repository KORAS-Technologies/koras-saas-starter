"""Turning what arrived into what the definition says it is, or refusing it.

One path, borrowed from `koras_reporting.filters._coerce`, and borrowed rather
than reinvented because the two do the same job: a definition decides, an enum
must be among its options, a number must parse and respect its bounds, and an
unknown key is **refused rather than ignored**.

That last property is the one worth stating. A write that silently drops a key
it does not recognise answers 200 to a request that changed nothing, and the
person who sent it has no way to tell that from success. Reporting refuses
unknown filter keys for exactly this reason (`filters.py:111-113`) and so does
this.

Nothing here touches a database, a tenant or a session. It is given a value and
a definition and it either returns a value or raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .definitions import DataType, Scope, SettingDefinition, SettingValue


class SettingError(ValueError):
    """A value, a key or a scope the framework refuses.

    Carries the key so a caller building an API error does not have to
    reconstruct which of several settings in one request was the bad one.
    """

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
        self.message = message


class ScopeRefused(SettingError):
    """The value is fine; this scope may not hold it.

    A distinct class because the two failures deserve different answers: a
    value outside its bounds is a 422 the sender can fix by sending another
    one, and a scope that may not hold it is a 403 no value would satisfy.
    """


def coerce(definition: SettingDefinition, raw: Any) -> SettingValue:  # noqa: ANN401
    """The value this definition would store, or a refusal.

    `raw` is deliberately untyped. It has come off a JSON body or out of a
    `jsonb` column, so it is whatever the sender or the row held; deciding what
    it is is this function's entire job, and annotating it as something
    narrower would be a claim made before the check.
    """
    match definition.data_type:
        case DataType.BOOLEAN:
            return _boolean(definition, raw)
        case DataType.INTEGER:
            return _integer(definition, raw)
        case DataType.DECIMAL:
            return _decimal(definition, raw)
        case DataType.STRING:
            return _string(definition, raw)
        case DataType.ENUM:
            return _enum(definition, raw)
        case DataType.STRING_LIST:
            return _string_list(definition, raw)
        case DataType.OBJECT:
            return _object(definition, raw)


def _boolean(definition: SettingDefinition, raw: Any) -> bool:  # noqa: ANN401
    if isinstance(raw, bool):
        return raw
    raise SettingError(definition.key, f"{definition.key} is true or false")


def _integer(definition: SettingDefinition, raw: Any) -> int:  # noqa: ANN401
    # `bool` first: in Python `True` is an `int`, so a checkbox posted into a
    # number would otherwise store 1 and read back as a perfectly valid count.
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise SettingError(definition.key, f"{definition.key} is a whole number")
    return int(_within_bounds(definition, raw))


def _decimal(definition: SettingDefinition, raw: Any) -> float:  # noqa: ANN401
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SettingError(definition.key, f"{definition.key} is a number")
    return float(_within_bounds(definition, float(raw)))


def _within_bounds(definition: SettingDefinition, value: float) -> float:
    if definition.minimum is not None and value < definition.minimum:
        raise SettingError(
            definition.key, f"{definition.key} is at least {_plain(definition.minimum)}"
        )
    if definition.maximum is not None and value > definition.maximum:
        raise SettingError(
            definition.key, f"{definition.key} is at most {_plain(definition.maximum)}"
        )
    return value


def _plain(bound: float) -> str:
    """A bound as a person would write it.

    `50.0` in a sentence about a row count reads as a rounding error somebody
    should look into. Bounds are declared as floats because decimals share the
    field; most of them are whole numbers.
    """
    return str(int(bound)) if bound == int(bound) else str(bound)


def _string(definition: SettingDefinition, raw: Any) -> str:  # noqa: ANN401
    if not isinstance(raw, str):
        raise SettingError(definition.key, f"{definition.key} is text")
    return raw


def _enum(definition: SettingDefinition, raw: Any) -> str:  # noqa: ANN401
    if not isinstance(raw, str) or raw not in definition.options:
        allowed = ", ".join(definition.options)
        raise SettingError(definition.key, f"{definition.key} is one of: {allowed}")
    return raw


def _string_list(definition: SettingDefinition, raw: Any) -> tuple[str, ...]:  # noqa: ANN401
    # A tuple as well as a list: a value read back out of `jsonb` is a list, and
    # a value round-tripped through a definition's default is a tuple.
    if not isinstance(raw, (list, tuple)) or not all(isinstance(item, str) for item in raw):
        raise SettingError(definition.key, f"{definition.key} is a list of text values")
    return tuple(raw)


def _object(definition: SettingDefinition, raw: Any) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise SettingError(definition.key, f"{definition.key} is an object")
    return dict(raw)


def check_writable(definition: SettingDefinition, scope: Scope) -> None:
    """Whether this scope may hold a value for this setting at all.

    The brief's rule, enforced in one place: a person may never override a
    setting whose scope is not the three-level one, and an organisation may
    never modify a platform-only setting. Both are refusals about the scope
    rather than the value, so both raise `ScopeRefused` and both become a 403.

    A caller passes the scope it is writing *at* -- `Scope.GLOBAL_ORG_USER`
    for a person's own preference, `Scope.GLOBAL_ORG` for an organisation's.
    Reading the argument as "the rung I am on" rather than "the ladder this
    setting has" is what makes the two comparisons below the right way round.
    """
    if scope is Scope.GLOBAL_ORG_USER and not definition.scope.admits_user:
        raise ScopeRefused(
            definition.key,
            f"{definition.key} is set for the whole organisation and cannot be "
            "overridden by one person",
        )
    if scope is Scope.GLOBAL_ORG and not definition.scope.admits_organization:
        raise ScopeRefused(
            definition.key,
            f"{definition.key} is set by the platform and cannot be changed here",
        )


def valid(definition: SettingDefinition, raw: Any) -> bool:  # noqa: ANN401
    """Whether a stored value still satisfies its definition.

    Used by the resolver on the way *out*, not on the way in. A bound tightened
    or an option withdrawn in a deploy leaves rows behind that were valid when
    they were written; the resolver falls through to the next level rather than
    refusing to render the page, and reports what it skipped.
    """
    try:
        coerce(definition, raw)
    except SettingError:
        return False
    return True
