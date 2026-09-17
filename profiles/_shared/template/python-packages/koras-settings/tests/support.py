"""One builder, so a test says only what it is about.

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
