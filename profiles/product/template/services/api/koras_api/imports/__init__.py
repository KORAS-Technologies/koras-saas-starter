"""The product's import catalogue, built once at import.

The same shape as `koras_api.reporting`: a registry assembled from the starter's
own declarations and the product's, at import, so a duplicate key is a
traceback before the process starts rather than a 500 for a customer.

The starter declares none, so today the registry is the product's alone —
stated rather than implied, because a reader coming from `reporting/__init__.py`
would reasonably expect a `standard.py` beside it and there is no such thing.
An import target names a table the product owns; a starter target would be the
starter guessing at a domain it does not have.

**The worker reads this module by name**, the way `tasks/reporting.py` reads the
report catalogue: the image carries `koras_api/imports/` alone, put on the path
by the Dockerfile, so a validation job can see what a target declares without
the worker depending on the API's distribution. The two background task
*declarations* are not here for the same reason — they are in `koras_import`,
because the worker's function list needs them at import and a graceful
`importlib` failure there would be a worker that accepts a job it can never run.
"""

from koras_import import TargetRegistry, build_registry

from . import targets

#: Every target this product accepts. Built at import; immutable thereafter,
#: for the reason the AI registries give: a target registered per request would
#: be a target that exists for some callers and not others.
registry: TargetRegistry = build_registry(targets.TARGETS)

__all__ = ["registry"]
