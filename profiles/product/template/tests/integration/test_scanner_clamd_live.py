# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""The scanner client against a real clamd (ADR 0013, `secure_files`).

`test_scanner_foundation.py` proves the client against a fake daemon that says whatever a test
scripts. This is the same client against the service this product deploys
(`services/clamd`), to show that the answers the parser was written for are the answers the
engine gives: the protocol, the EICAR detection, an ordinary file's `OK`, and what an unreachable
or limit-exceeding input looks like. It also states, against the real engine, the one thing the
product relies on and the engine does not do: a deflated, streamed ZIP64 entry answers `OK`
without being inspected, so `OK` is only ever a candidate (`docs/CLAMD_SERVICE.md`).

Needs a running clamd: set `E2E_CLAMD_HOST` (and `E2E_CLAMD_PORT`, default 3310). It is generated
only into a product with `secure_files`, where the generator-integration workflow starts the
service from `services/clamd` and fails on any skip.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HOST = os.environ.get("E2E_CLAMD_HOST", "")
PORT = int(os.environ.get("E2E_CLAMD_PORT", "3310"))
# The worker's settings are read when its modules are first imported, and this file may be the
# first to import them: give them the database the other integration suites name.
if os.environ.get("E2E_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["E2E_DATABASE_URL"]
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.skipif(not HOST, reason="needs a running clamd (E2E_CLAMD_HOST)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from eicar_support import materialize  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    ClamdScanner,
    ScannerSettings,
    ScanOutcome,
    resolve_scanner,
)
from koras_worker.scanning.config import MAX_SCAN_BYTES  # noqa: E402
from scanner_support import blocks  # noqa: E402
from zip_support import real_docx, streamed_zip  # noqa: E402


def client(**overrides) -> ClamdScanner:
    values = {
        "host": HOST,
        "port": PORT,
        "connect_timeout": 5.0,
        "scan_timeout": 60.0,
        "max_bytes": MAX_SCAN_BYTES,
    }
    values.update(overrides)
    return ClamdScanner(**values)


async def test_the_service_answers_ping() -> None:
    assert await client().ping() is True


async def test_an_ordinary_document_is_a_candidate_never_a_release() -> None:
    result = await client().scan(blocks(b"name,amount\nacme,10\n"))
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN
    assert result.candidate_clean and result.requires_structural_gate


async def test_a_genuine_office_document_is_a_candidate() -> None:
    result = await client().scan(blocks(real_docx()))
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN


async def test_eicar_is_infected_whatever_the_chunking() -> None:
    sample = materialize()
    whole = await client().scan(blocks(sample))
    assert whole.outcome is ScanOutcome.INFECTED
    pieces = await client().scan(blocks(*(sample[i : i + 7] for i in range(0, len(sample), 7))))
    assert pieces.outcome is ScanOutcome.INFECTED
    assert not hasattr(whole, "signature"), "a signature name is classified and dropped"


async def test_eicar_in_an_ordinary_archive_is_found() -> None:
    body = streamed_zip(force_zip64=False, payload=materialize())
    assert (await client().scan(blocks(body))).outcome is ScanOutcome.INFECTED


async def test_a_streamed_deflated_zip64_entry_is_a_candidate_or_a_detection_never_a_release() -> None:
    """The documented engine gap. If the engine ever finds it this stays green and the
    structural gate stays in place; `services/clamd`'s own image test is the tripwire."""
    body = streamed_zip(force_zip64=True, payload=materialize())
    result = await client().scan(blocks(body))
    assert result.outcome in {ScanOutcome.CANDIDATE_CLEAN, ScanOutcome.INFECTED}


async def test_the_engine_answers_ok_for_a_benign_streamed_zip64_archive() -> None:
    """A candidate, and the product's structural gate is what decides it is not released."""
    result = await client().scan(blocks(streamed_zip(force_zip64=True)))
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN


async def test_an_input_over_the_clients_ceiling_is_a_limit_not_a_pass() -> None:
    result = await client(max_bytes=16).scan(blocks(b"x" * 64))
    assert result.outcome is ScanOutcome.LIMIT_EXCEEDED
    assert not result.candidate_clean


async def test_an_unreachable_scanner_is_unavailable_and_never_clean() -> None:
    result = await client(host="127.0.0.1", port=9, connect_timeout=1.0).scan(blocks(b"x"))
    assert result.outcome is ScanOutcome.UNAVAILABLE
    assert not result.candidate_clean
    assert await client(host="127.0.0.1", port=9, connect_timeout=1.0).ping() is False


async def test_the_resolved_scanner_is_the_one_the_operator_named() -> None:
    scanner = resolve_scanner(
        ScannerSettings(
            file_scan_backend="clamd", file_scan_clamd_host=HOST, file_scan_clamd_port=PORT
        )
    )
    assert isinstance(scanner, ClamdScanner)
    assert await scanner.ping() is True
    assert (await scanner.scan(blocks(materialize()))).outcome is ScanOutcome.INFECTED
