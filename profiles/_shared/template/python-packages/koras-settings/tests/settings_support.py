"""One builder, so a test says only what it is about.

**Named for its package, not `support`.** Every `python-packages/*/tests/`
directory is on the path as a top-level module, with no `__init__.py`, so two
packages each carrying a `support.py` are two modules with one name -- and
`mypy` refuses the pair rather than choosing. `koras-ai` got there first;
`tests/unit/reporting_support.py` in the product already follows the same rule.
Found by CI on 2026-09-17, which is the only place it shows: a single package's
suite runs perfectly well on its own.

Every suite here needs a definition and almost none of them care what it says.
A factory with overrides means a test about enum options names options and
nothing else, which is what makes the failure message useful when one breaks.
"""

from __future__ import annotations

from typing import Any

from koras_settings import Category, DataType, Scope, SettingDefinition


def setting(key: str = "grid.pageSize", **overrides: Any) -> SettingDefinition:  # noqa: ANN401
    fields: dict[str, Any] = {
        "key": key,
        "category": Category.GRID,
        "data_type": DataType.INTEGER,
        "default": 50,
        "scope": Scope.GLOBAL_ORG_USER,
        "label_key": "settings.grid.pageSize.label",
        "description_key": "settings.grid.pageSize.description",
        "minimum": 10,
        "maximum": 500,
    }
    fields.update(overrides)
    return SettingDefinition(**fields)
