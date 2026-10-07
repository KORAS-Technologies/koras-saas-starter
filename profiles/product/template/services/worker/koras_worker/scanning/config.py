"""Scanner configuration, and the one place a scanner is chosen.

**The backend is chosen by the operator, and fails closed.** `FILE_SCAN_BACKEND` is `none`
unless set, and the only other value is `clamd`. Anything else fails settings validation, so a
typo stops the worker rather than quietly selecting nothing. `none` resolves to a scanner that
answers `MISCONFIGURED` for every scan: "no scanner" is an unavailable scanner, never a clean
one. In a product generated with `secure_files` the backend `none` is a startup error and has
no exception (`koras_worker.secure_files`); this module is the second line, so that a job
which somehow ran with no scanner still holds the file and releases nothing.

**The address is the operator's, never an input.** `FILE_SCAN_CLAMD_HOST` and
`FILE_SCAN_CLAMD_PORT` name the private clamd service this product deployed (see
`docs/CLAMD_SERVICE.md`). There is no host a tenant, a request or a file can influence, and
no credential, because clamd's listener has none. A blank host resolves to an unavailable
scanner rather than a default: a worker with no named scanner scans nothing.

**Limits are settings with bounded ranges.** Each can be tightened and none can be loosened
past the value the clamd service is built for: `FILE_SCAN_MAX_BYTES` can lower the ceiling and
can never raise it past `MAX_SCAN_BYTES`, because clamd's `StreamMaxLength` is that value.
`koras_worker.secure_files` checks the same ranges at start, so a worker with a limit outside
its range refuses to start; the model validators here are the same rules a second time.

The product's own sweeps share one rule about blank values -- a cleared box in the secret
store means "absent" -- and this class inherits it from `SweepSettings`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from typing import Literal

from pydantic import Field, model_validator

from ..settings import SweepSettings
from .clamd import ClamdScanner
from .protocol import Scanner
from .result import ScanOutcome, ScanResult

logger = logging.getLogger(__name__)

MIB = 1024 * 1024

#: The supported input ceiling. clamd's `StreamMaxLength` in `services/clamd/clamd.conf` is
#: 100M, so nothing larger may be sent. The setting can lower the ceiling and can never raise
#: it past this. The scan sweep's partial indexes (migration 00041) carry the same number.
MAX_SCAN_BYTES = 100 * MIB

#: `files.scan_attempts` is a smallint and saturates here rather than wrapping.
MAX_RECORDED_ATTEMPTS = 32767

#: The ranges of the numeric settings. `koras_worker.secure_files` states the same ones.
MAX_CONNECT_TIMEOUT_SECONDS = 60
MAX_SCAN_TIMEOUT_SECONDS = 600


class ScannerConfigurationError(ValueError):
    """The backend named is not one this code knows. Never resolves to a scanner."""


class ScannerSettings(SweepSettings):
    """The scanner client's settings. Read by the worker only; none is a secret."""

    file_scan_backend: Literal["none", "clamd"] = "none"
    #: The private address of this product's clamd service. Required for a scanner to exist.
    file_scan_clamd_host: str = ""
    file_scan_clamd_port: int = Field(default=3310, ge=1, le=65535)
    file_scan_connect_timeout_seconds: float = Field(
        default=5.0, gt=0, le=MAX_CONNECT_TIMEOUT_SECONDS
    )
    file_scan_timeout_seconds: float = Field(default=120.0, gt=0, le=MAX_SCAN_TIMEOUT_SECONDS)
    file_scan_max_bytes: int = Field(default=MAX_SCAN_BYTES, gt=0, le=MAX_SCAN_BYTES)
    #: The attempt count at which `scan_exhausted` is written, once. An operational
    #: signal, not a limit on retrying: the file stays pending and in the sweep.
    #: Capped at the column's saturation point.
    file_scan_max_attempts: int = Field(default=12, ge=1, le=MAX_RECORDED_ATTEMPTS)

    @model_validator(mode="after")
    def _connect_within_scan(self) -> ScannerSettings:
        if self.file_scan_connect_timeout_seconds > self.file_scan_timeout_seconds:
            raise ValueError("the connect timeout cannot exceed the scan timeout")
        return self


def scanner_active(backend: str) -> bool:
    """Whether a scanner can answer: the one rule for "the sweep has something to enqueue for".

    Only the real backend. Anything else is "not activated", and the sweep enqueues nothing:
    with no scanner a job could only record a `misconfigured` hold per file, which is noise
    about a decision nobody made. This does not loosen anything: `pending` is withheld.
    """
    return backend == "clamd"


class UnavailableScanner:
    """A scanner that cannot scan: backend `none`, or a configuration refused.

    Every scan is `MISCONFIGURED` and `ping` is false. It reads nothing from the
    source and connects to nothing, so it has no path to a pass.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def scan(self, source: AsyncIterable[bytes]) -> ScanResult:
        return ScanResult(ScanOutcome.MISCONFIGURED)

    async def ping(self) -> bool:
        return False


def resolve_scanner(config: ScannerSettings) -> Scanner:
    """The scanner this worker uses. The only constructor of a real one.

    Names are logged on refusal and values are not: the setting that was wrong,
    not what it was set to.
    """
    backend: str = config.file_scan_backend
    if backend == "none":
        return UnavailableScanner("backend none")
    if backend != "clamd":
        raise ScannerConfigurationError(f"unknown scanner backend {backend!r}")

    host = config.file_scan_clamd_host.strip()
    if not host:
        logger.error("scanner backend clamd refused: FILE_SCAN_CLAMD_HOST is not set")
        return UnavailableScanner("no host")

    return ClamdScanner(
        host=host,
        port=config.file_scan_clamd_port,
        connect_timeout=config.file_scan_connect_timeout_seconds,
        scan_timeout=config.file_scan_timeout_seconds,
        max_bytes=config.file_scan_max_bytes,
    )
