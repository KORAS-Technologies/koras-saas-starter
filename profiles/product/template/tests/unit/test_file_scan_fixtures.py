"""The legacy scan seam, exercised with the EICAR sample (`secure_files`).

`core/file_scan.py` is the seam a scanner plugs into in a product without the capability:
`record_scan` writes what a scan found, and `withheld` is the one function every download and
list path consults. A product with the capability keeps `withheld` (the files router still asks
it) and adds the worker's guarded transitions, which are the only writer of a clean verdict;
there `record_scan` raises, so the unconditional writer cannot be called by accident. This keeps
the seam itself honest with the EICAR sample standing in for the file a real scanner would
flag. The sample is assembled at run time (`eicar_support`), never stored.
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

import pytest
from eicar_support import EICAR_SHA256, materialize  # noqa: E402
from koras_api.core.file_scan import record_scan, withheld  # noqa: E402
from koras_api.core.secure_files import SECURE_FILES  # noqa: E402


class _Rows:
    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.calls.append((str(statement), parameters))
        return _Rows()

    async def commit(self) -> None:
        self.calls.append(("commit", None))


def test_the_eicar_sample_is_the_real_68_byte_standard_string() -> None:
    """The sample is the unmodified standard string, not a look-alike -- a scanner must
    recognise it, which only the exact bytes guarantee."""
    import hashlib

    raw = materialize()
    assert hashlib.sha256(raw).hexdigest() == EICAR_SHA256
    assert len(raw) == 68
    assert raw.startswith(rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE")


@pytest.mark.parametrize("clean_status", ["pending", "clean", "skipped"])
def test_only_infected_is_withheld(clean_status: str) -> None:
    assert withheld(clean_status) is False
    assert withheld(None) is False  # pending is the default for a null status


async def test_a_scanner_finding_the_eicar_fixture_infected_withholds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path a real scanner would take: it reads the object (here, the
    EICAR fixture standing in for it), decides `infected`, and calls
    `record_scan`. After that, `withheld("infected")` -- the same function the
    download route and the file listing both consult -- must say yes."""
    raw = materialize()
    assert len(raw) == 68  # the scanner read a real, complete file

    if SECURE_FILES:
        # With the capability this seam is closed: a verdict has exactly one writer, the
        # worker's guarded transitions, and a call here raises before it touches the session.
        refused = _Session()
        for status in ("infected", "clean", "skipped", "pending"):
            with pytest.raises(RuntimeError, match="record_scan is disabled"):
                await record_scan(
                    refused,  # type: ignore[arg-type]
                    tenant_id="tenant-1",
                    file_id="file-1",
                    status=status,  # type: ignore[arg-type]
                    note="x",
                )
        assert refused.calls == []
        return

    session = _Session()

    async def rebind(bound: object, tenant_id: str) -> None:
        session.calls.append(("rebind", None))

    from koras_api.core import audit as core_audit

    monkeypatch.setattr(core_audit, "rebind_tenant", rebind)

    await record_scan(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        file_id="file-1",
        status="infected",
        note="matched the EICAR test signature",
    )

    quarantine_call = next(call for call in session.calls if "quarantined" in call[0])
    assert quarantine_call[1] == {
        "status": "infected",
        "note": "matched the EICAR test signature",
        "file_id": "file-1",
        "tenant_id": "tenant-1",
    }
    assert withheld("infected") is True
