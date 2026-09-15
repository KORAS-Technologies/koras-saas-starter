"""The catalogue: the standard tenant reports and this product's own, built
once at import.

The same shape as `koras_api.ai`: registries are configuration, assembled
where the definitions live and refused at import when a report names a
metric nobody registered or two reports share a key. A product edits
`reports.py`; `standard.py` is the starter's and is replaced by a sync.
"""

from __future__ import annotations

from koras_reporting import ReportingCatalogue, build_catalogue

from . import reports, standard

catalogue: ReportingCatalogue = build_catalogue(
    [*standard.METRICS, *reports.METRICS],
    [*standard.REPORTS, *reports.REPORTS],
)

__all__ = ["catalogue"]
