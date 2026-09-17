"""The catalogue for this process, assembled once.

The foundation's definitions and the product's own, in that order, so a
collision's traceback names the product's file as the one that was being added.

Built at import. A duplicate key, a default outside its own bounds or a
definition offering a person an override nothing would honour is a failure to
start rather than a 500 on the settings page -- the property
`koras_reporting.build_catalogue` has and the reason it has it.
"""

from __future__ import annotations

from koras_settings import SettingsRegistry, build_catalogue

from . import product, standard

catalogue: SettingsRegistry = build_catalogue(standard.SETTINGS, product.SETTINGS)

__all__ = ["catalogue"]
