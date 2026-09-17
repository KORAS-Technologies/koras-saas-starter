"""Settings this product adds to the foundation's.

Ships empty. A product that needs a setting of its own declares it here and
nothing else changes: the registry picks it up at import, the API publishes it,
the settings pages render it from its own metadata, and provisioning copies it
into every tenant created afterwards.

The extension point reporting has, in the same shape and for the same reason --
`reporting/reports.py` ships an empty `REPORTS` list with a worked example.

A worked example, for a shop that lets an organisation decide how long a basket
is held:

    from koras_settings import Category, DataType, Scope, SettingDefinition, UiControl

    SETTINGS: list[SettingDefinition] = [
        SettingDefinition(
            key="shop.basketHoldMinutes",
            category=Category.GENERAL,
            data_type=DataType.INTEGER,
            default=30,
            scope=Scope.GLOBAL_ORG,
            label_key="settings.def.shop.basketHoldMinutes.label",
            description_key="settings.def.shop.basketHoldMinutes.description",
            minimum=5,
            maximum=1440,
            user_visible=False,
            ui=UiControl.NUMBER,
            order=10,
        ),
    ]

Three things that example shows and a first attempt usually misses:

- `user_visible=False` is required, not optional. The scope admits no personal
  override, and a definition offering one to a person is refused at import.
- The two i18n keys must exist in every catalogue in `packages/i18n`, or the
  generator's structural test says which language is behind.
- A key that collides with a foundation setting is refused at import. That is
  the point: silently shadowing one would mean two definitions and no way to
  say which is being read.
"""

from __future__ import annotations

from koras_settings import SettingDefinition

SETTINGS: list[SettingDefinition] = []
