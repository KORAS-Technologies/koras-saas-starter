"""The one result shape every promotion check returns, and the one rule for combining them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["PASS", "FAIL"]
#: The four environments of a generated product (`profiles/product/manifest.yaml`); `prod` is
#: branch `main`. A product that names another environment is refused by `config.py`.
ENVIRONMENTS = ("dev", "test", "stg", "prod")


@dataclass(frozen=True, slots=True)
class Check:
    """`id` is a stable slug (`activation_config`, `f1_unverified_releasable`, ...). `detail` is one
    line a person can act on and never contains a secret, an object key or a file name. `data`
    holds counts and identifiers (tenant and file uuids), JSON-serialisable."""

    id: str
    status: Status
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def fail(check_id: str, detail: str, **data: Any) -> Check:  # noqa: ANN401
    return Check(check_id, "FAIL", detail, dict(data))


def ok(check_id: str, detail: str, **data: Any) -> Check:  # noqa: ANN401
    return Check(check_id, "PASS", detail, dict(data))


def overall(checks: list[Check]) -> Status:
    """PASS only when there is at least one check and every check passed."""
    return "PASS" if checks and all(c.passed for c in checks) else "FAIL"
