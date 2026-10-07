"""The scanner contract, the ClamAV client and the scanner settings (`secure_files`).

Against a fake clamd on a loopback socket, never a real scanner. What is
asserted is the fail-closed shape: every outcome that is not a detection or an
engine `OK` is a hold, a malformed reply is never a pass, and an engine `OK` is
only ever a candidate -- the model has no way to say a file is `clean`.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    MAX_SCAN_BYTES,
    ClamdScanner,
    Disposition,
    ScanFailure,
    ScannerConfigurationError,
    ScannerSettings,
    ScanOutcome,
    ScanResult,
    UnavailableScanner,
    parse_reply,
    resolve_scanner,
)
from koras_worker.scanning.result import IncompleteKind  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from scanner_support import (  # noqa: E402
    FakeScanner,
    blocks,
    closed_port,
    dropping,
    failing_source,
    hanging,
    hanging_up,
    replying,
    replying_early,
    serving,
)

SCANNING_DIR = Path(scanning.__file__).parent


def client(port: int, **overrides: float) -> ClamdScanner:
    values: dict[str, float] = {
        "connect_timeout": 2.0,
        "scan_timeout": 5.0,
        "max_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return ClamdScanner(
        host="127.0.0.1",
        port=port,
        connect_timeout=values["connect_timeout"],
        scan_timeout=values["scan_timeout"],
        max_bytes=int(values["max_bytes"]),
    )


# --- the reply parser ---------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        ("stream: OK", ScanOutcome.CANDIDATE_CLEAN),
        ("stream: Win.Test.EICAR_HDB-1 FOUND", ScanOutcome.INFECTED),
        ("stream: Eicar-Signature FOUND", ScanOutcome.INFECTED),
        (
            "stream: Heuristics.Phishing.Email.SpoofedDomain FOUND",
            ScanOutcome.INCOMPLETE_INSPECTION,
        ),
        ("stream: Heuristics.Broken.Executable FOUND", ScanOutcome.INCOMPLETE_INSPECTION),
        ("stream: Heuristics.OLE2.ContainsMacros FOUND", ScanOutcome.INCOMPLETE_INSPECTION),
        ("stream: Heuristics.Structured.SSN_Formatted FOUND", ScanOutcome.INCOMPLETE_INSPECTION),
        ("stream: Win.Heuristics.NotAPrefix FOUND", ScanOutcome.INFECTED),
        ("stream: Heuristics.Encrypted.Zip FOUND", ScanOutcome.INCOMPLETE_INSPECTION),
        ("stream: Heuristics.Encrypted.PDF FOUND", ScanOutcome.INCOMPLETE_INSPECTION),
        ("stream: Heuristics.Limits.Exceeded.MaxFileSize FOUND", ScanOutcome.LIMIT_EXCEEDED),
        ("INSTREAM size limit exceeded. ERROR", ScanOutcome.LIMIT_EXCEEDED),
        ("Can't allocate memory ERROR", ScanOutcome.SCANNER_ERROR),
    ],
)
def test_reply_shapes(reply: str, outcome: ScanOutcome) -> None:
    assert parse_reply(reply).outcome is outcome


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "OK",
        "stream: ok",
        "stream: OK ",
        " stream: OK",
        "stream:OK",
        "stream: OK\nstream: Eicar FOUND",
        "stream:  FOUND",
        "stream: two words FOUND",
        "stream: Eicar FOUND trailing",
        "PONG",
        "stream: OK ERROR",
        "ERROR",
        "garbage\x01\x02",
        "stream: " + "A" * 300 + " FOUND",
        "x" * 5000,
    ],
)
def test_anything_unrecognised_is_malformed_never_clean(reply: str) -> None:
    result = parse_reply(reply)
    assert result.outcome is ScanOutcome.MALFORMED_RESPONSE or result.outcome is (
        ScanOutcome.SCANNER_ERROR
    )
    assert not result.candidate_clean


def test_encrypted_is_a_hold_with_a_kind_and_not_a_detection() -> None:
    result = parse_reply("stream: Heuristics.Encrypted.Zip FOUND")
    assert result.incomplete_kind is IncompleteKind.ENCRYPTED
    assert result.disposition is Disposition.HOLD_UNINSPECTABLE
    assert result.failure is ScanFailure.INSPECTION_INCOMPLETE


@pytest.mark.parametrize(
    "signature",
    [
        "Heuristics.Phishing.Email.SpoofedDomain",
        "Heuristics.Broken.Executable",
        "Heuristics.OLE2.ContainsMacros",
        "Heuristics.Structured.CreditCardNumber",
        "Heuristics.Anything.Else.At.All",
    ],
)
def test_every_heuristics_found_is_an_incomplete_hold_not_a_detection(signature: str) -> None:
    result = parse_reply(f"stream: {signature} FOUND")
    assert result.outcome is ScanOutcome.INCOMPLETE_INSPECTION
    assert result.disposition is Disposition.HOLD_UNINSPECTABLE
    assert result.failure is ScanFailure.INSPECTION_INCOMPLETE
    assert not result.candidate_clean
    assert result.disposition is not Disposition.INFECTED


def test_ordinary_malware_is_still_infected_and_limits_keep_their_own_failure() -> None:
    assert parse_reply("stream: Win.Test.EICAR_HDB-1 FOUND").disposition is Disposition.INFECTED
    limit = parse_reply("stream: Heuristics.Limits.Exceeded.MaxScanSize FOUND")
    assert limit.failure is ScanFailure.SCAN_LIMIT_EXCEEDED
    assert limit.disposition is Disposition.HOLD_UNINSPECTABLE


def test_result_carries_no_signature_text() -> None:
    result = parse_reply("stream: Win.Test.EICAR_HDB-1 FOUND")
    assert "EICAR" not in repr(result)
    assert {f for f in ScanResult.__dataclass_fields__} == {
        "outcome",
        "incomplete_kind",
        "bytes_sent",
    }


# --- the result model and the release rule ------------------------------------


def test_the_model_has_no_clean_outcome_or_disposition() -> None:
    assert "clean" not in {o.value for o in ScanOutcome}
    assert "clean" not in {d.value for d in Disposition}
    assert not hasattr(ScanResult(ScanOutcome.CANDIDATE_CLEAN), "clean")
    assert not hasattr(ScanResult(ScanOutcome.CANDIDATE_CLEAN), "is_clean")


def test_scanner_ok_is_a_candidate_that_still_requires_the_structural_gate() -> None:
    ok = parse_reply("stream: OK")
    assert ok.candidate_clean
    assert ok.requires_structural_gate
    assert ok.disposition is Disposition.CANDIDATE_CLEAN
    assert ok.failure is None


def test_only_a_candidate_clean_requires_the_structural_gate() -> None:
    for outcome in ScanOutcome:
        kind = IncompleteKind.INCOMPLETE if outcome is ScanOutcome.INCOMPLETE_INSPECTION else None
        result = ScanResult(outcome, kind)
        assert result.requires_structural_gate is (outcome is ScanOutcome.CANDIDATE_CLEAN)


@pytest.mark.parametrize("outcome", list(ScanOutcome))
def test_every_non_verdict_outcome_is_a_hold_with_a_failure_class(outcome: ScanOutcome) -> None:
    kind = IncompleteKind.INCOMPLETE if outcome is ScanOutcome.INCOMPLETE_INSPECTION else None
    result = ScanResult(outcome, kind)
    if outcome in (ScanOutcome.CANDIDATE_CLEAN, ScanOutcome.INFECTED):
        assert result.failure is None
    else:
        assert result.failure is not None
        assert result.disposition in (Disposition.HOLD_RETRY, Disposition.HOLD_UNINSPECTABLE)


def test_limit_and_incomplete_are_not_retryable_but_operational_failures_are() -> None:
    assert ScanResult(ScanOutcome.LIMIT_EXCEEDED).disposition is Disposition.HOLD_UNINSPECTABLE
    for outcome in (
        ScanOutcome.UNAVAILABLE,
        ScanOutcome.TIMEOUT,
        ScanOutcome.MALFORMED_RESPONSE,
        ScanOutcome.SCANNER_ERROR,
        ScanOutcome.READ_FAILURE,
        ScanOutcome.MISCONFIGURED,
    ):
        assert ScanResult(outcome).disposition is Disposition.HOLD_RETRY


def test_incomplete_kind_belongs_only_to_incomplete_inspection() -> None:
    with pytest.raises(ValueError, match="incomplete_kind"):
        ScanResult(ScanOutcome.CANDIDATE_CLEAN, IncompleteKind.ENCRYPTED)
    with pytest.raises(ValueError, match="incomplete_kind"):
        ScanResult(ScanOutcome.INCOMPLETE_INSPECTION)


# --- the ClamAV client against a fake clamd -----------------------------------


async def test_ping_pong() -> None:
    async with serving(lambda fake: replying(fake, b"PONG\0")) as fake:
        assert await client(fake.port).ping() is True
        assert fake.commands == [b"zPING\0"]


async def test_ping_with_an_unexpected_reply_is_false() -> None:
    async with serving(lambda fake: replying(fake, b"NOPE\0")) as fake:
        assert await client(fake.port).ping() is False


async def test_ping_refused_is_false() -> None:
    assert await client(await closed_port()).ping() is False


async def test_ping_hang_is_false_within_the_connect_timeout() -> None:
    async with serving(hanging) as fake:
        assert await client(fake.port, connect_timeout=0.2).ping() is False


async def test_benign_reply_is_a_candidate_clean_and_the_stream_is_framed() -> None:
    payload = b"hello " * 50_000  # 300 kB: split into several chunks
    async with serving(lambda fake: replying(fake, b"stream: OK\0")) as fake:
        result = await client(fake.port).scan(blocks(payload[:100_000], payload[100_000:]))
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN
    assert result.bytes_sent == len(payload)
    assert bytes(fake.streamed) == payload
    assert fake.terminated
    assert fake.commands == [b"zINSTREAM\0"]


async def test_an_empty_object_is_still_only_a_candidate() -> None:
    async with serving(lambda fake: replying(fake, b"stream: OK\0")) as fake:
        result = await client(fake.port).scan(blocks())
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN
    assert fake.terminated


async def test_found_is_infected() -> None:
    async with serving(lambda fake: replying(fake, b"stream: Eicar-Signature FOUND\0")) as fake:
        result = await client(fake.port).scan(blocks(b"X5O!P%@AP"))
    assert result.outcome is ScanOutcome.INFECTED
    assert result.disposition is Disposition.INFECTED


async def test_encrypted_heuristic_found_is_held_not_infected_not_clean() -> None:
    reply = b"stream: Heuristics.Encrypted.Zip FOUND\0"
    async with serving(lambda fake: replying(fake, reply)) as fake:
        result = await client(fake.port).scan(blocks(b"PK"))
    assert result.outcome is ScanOutcome.INCOMPLETE_INSPECTION
    assert result.incomplete_kind is IncompleteKind.ENCRYPTED
    assert not result.candidate_clean


async def test_server_side_size_limit_reply_is_limit_exceeded() -> None:
    reply = b"INSTREAM size limit exceeded. ERROR\0"
    async with serving(lambda fake: replying(fake, reply)) as fake:
        result = await client(fake.port).scan(blocks(b"a" * 1000))
    assert result.outcome is ScanOutcome.LIMIT_EXCEEDED


async def test_server_that_answers_the_limit_early_and_hangs_up_is_limit_exceeded() -> None:
    reply = b"INSTREAM size limit exceeded. ERROR\0"
    async with serving(lambda fake: replying_early(fake, reply, after=64 * 1024)) as fake:
        result = await client(fake.port).scan(blocks(*[b"a" * 65536] * 40))
    # Whether the reply or the reset reaches the client first, the answer is a hold.
    assert result.outcome in (ScanOutcome.LIMIT_EXCEEDED, ScanOutcome.UNAVAILABLE)
    assert not result.candidate_clean


async def test_client_side_ceiling_stops_the_stream_without_a_terminator() -> None:
    async with serving(lambda fake: hanging_up(fake)) as fake:
        result = await client(fake.port, max_bytes=100_000).scan(blocks(b"a" * 300_000))
        await asyncio.sleep(0.05)
    assert result.outcome is ScanOutcome.LIMIT_EXCEEDED
    assert result.bytes_sent <= 100_000 + 65536
    assert not fake.terminated, "a truncated stream must never be completed for the engine"


async def test_an_object_exactly_at_the_ceiling_is_sent() -> None:
    async with serving(lambda fake: replying(fake, b"stream: OK\0")) as fake:
        result = await client(fake.port, max_bytes=65536).scan(blocks(b"a" * 65536))
    assert result.outcome is ScanOutcome.CANDIDATE_CLEAN


async def test_scan_timeout_is_a_timeout() -> None:
    async with serving(hanging) as fake:
        result = await client(fake.port, scan_timeout=0.3).scan(blocks(b"abc"))
    assert result.outcome is ScanOutcome.TIMEOUT
    assert result.failure is ScanFailure.SCAN_TIMEOUT
    assert not result.candidate_clean


async def test_a_source_that_hangs_counts_against_the_same_wall_clock() -> None:
    async def stalled() -> AsyncIterator[bytes]:
        yield b"a"
        await asyncio.sleep(30)
        yield b"b"

    async with serving(lambda fake: hanging_up(fake)) as fake:
        result = await client(fake.port, scan_timeout=0.3).scan(stalled())
    assert result.outcome is ScanOutcome.TIMEOUT


async def test_connection_refused_is_unavailable() -> None:
    result = await client(await closed_port()).scan(blocks(b"abc"))
    assert result.outcome is ScanOutcome.UNAVAILABLE
    assert result.failure is ScanFailure.SCANNER_UNAVAILABLE


async def test_unresolvable_host_is_unavailable() -> None:
    scanner = ClamdScanner("nonexistent.invalid", 3310, 2.0, 5.0, 1024)
    assert (await scanner.scan(blocks(b"abc"))).outcome is ScanOutcome.UNAVAILABLE


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        (b"stream: PWNED\0", ScanOutcome.MALFORMED_RESPONSE),
        (b"stream: OK\nstream: OK\0", ScanOutcome.MALFORMED_RESPONSE),
        (b"\xff\xfe\0", ScanOutcome.MALFORMED_RESPONSE),
        (b"\0", ScanOutcome.MALFORMED_RESPONSE),
        (b"stream: O", ScanOutcome.MALFORMED_RESPONSE),  # truncated, no terminator
        (b"stream: " + b"A" * 5000, ScanOutcome.MALFORMED_RESPONSE),  # oversized
        (b"PONG\0", ScanOutcome.MALFORMED_RESPONSE),  # a PING answer to an INSTREAM
        (b"UNKNOWN COMMAND\0", ScanOutcome.MALFORMED_RESPONSE),
        (b"", ScanOutcome.UNAVAILABLE),  # disconnect without a byte
    ],
)
async def test_unexpected_replies_fail_closed(reply: bytes, outcome: ScanOutcome) -> None:
    async with serving(lambda fake: replying(fake, reply)) as fake:
        result = await client(fake.port).scan(blocks(b"abc"))
    assert result.outcome is outcome
    assert not result.candidate_clean


async def test_scanner_that_hangs_up_after_the_stream_is_unavailable() -> None:
    async with serving(lambda fake: hanging_up(fake)) as fake:
        result = await client(fake.port).scan(blocks(b"abc"))
    assert result.outcome is ScanOutcome.UNAVAILABLE


async def test_scanner_that_drops_mid_stream_is_a_hold() -> None:
    async with serving(lambda fake: dropping(fake, after=65536)) as fake:
        result = await client(fake.port, max_bytes=100 * 1024 * 1024).scan(
            blocks(*[b"a" * 65536] * 40)
        )
    # Which way a reset surfaces depends on the platform's socket buffering, and
    # on Linux the client's own ceiling can trip first. Every one is a hold.
    assert result.outcome in (
        ScanOutcome.UNAVAILABLE,
        ScanOutcome.MALFORMED_RESPONSE,
        ScanOutcome.LIMIT_EXCEEDED,
    )
    assert not result.candidate_clean
    assert result.failure is not None


async def test_a_source_that_fails_is_a_read_failure_and_the_stream_is_not_completed() -> None:
    async with serving(lambda fake: hanging_up(fake)) as fake:
        result = await client(fake.port).scan(failing_source())
        await asyncio.sleep(0.05)
    assert result.outcome is ScanOutcome.READ_FAILURE
    assert result.failure is ScanFailure.OBJECT_UNREACHABLE
    assert not fake.terminated


# --- the fake scanner ---------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "outcome"),
    [
        (FakeScanner.candidate_clean, ScanOutcome.CANDIDATE_CLEAN),
        (FakeScanner.infected, ScanOutcome.INFECTED),
        (FakeScanner.timeout, ScanOutcome.TIMEOUT),
        (FakeScanner.unavailable, ScanOutcome.UNAVAILABLE),
        (FakeScanner.malformed, ScanOutcome.MALFORMED_RESPONSE),
        (FakeScanner.limit_exceeded, ScanOutcome.LIMIT_EXCEEDED),
    ],
)
async def test_fake_scanner_scripts_every_outcome(factory: object, outcome: ScanOutcome) -> None:
    fake = factory()  # type: ignore[operator]
    assert isinstance(fake, scanning.Scanner)
    result = await fake.scan(blocks(b"abc", b"def"))
    assert result.outcome is outcome
    assert fake.received == 6


async def test_fake_scanner_reports_an_unreadable_source() -> None:
    result = await FakeScanner.candidate_clean().scan(failing_source())
    assert result.outcome is ScanOutcome.READ_FAILURE


def test_the_real_clients_satisfy_the_contract() -> None:
    assert isinstance(ClamdScanner("h", 1, 1.0, 1.0, 1), scanning.Scanner)
    assert isinstance(UnavailableScanner("x"), scanning.Scanner)


# --- configuration ------------------------------------------------------------


def settings(**values: object) -> ScannerSettings:
    return ScannerSettings(**values)  # type: ignore[arg-type]


def test_the_default_backend_is_none_and_the_defaults_are_the_ratified_ones() -> None:
    cfg = settings()
    assert cfg.file_scan_backend == "none"
    assert cfg.file_scan_clamd_port == 3310
    assert cfg.file_scan_connect_timeout_seconds == 5
    assert cfg.file_scan_timeout_seconds == 120
    assert cfg.file_scan_max_bytes == 100 * 1024 * 1024 == MAX_SCAN_BYTES
    assert cfg.file_scan_clamd_host == ""


def test_a_blank_backend_is_none_not_an_error() -> None:
    assert settings(file_scan_backend="").file_scan_backend == "none"


@pytest.mark.parametrize("backend", ["ClamAV", "CLAMD", "clamav", "fake", "true", "1", "off"])
def test_an_unknown_backend_fails_settings_validation(backend: str) -> None:
    with pytest.raises(ValidationError):
        settings(file_scan_backend=backend)


def test_resolution_of_an_unvalidated_unknown_backend_raises_and_never_resolves() -> None:
    cfg = ScannerSettings.model_construct(file_scan_backend="fake")
    with pytest.raises(ScannerConfigurationError):
        resolve_scanner(cfg)


async def test_backend_none_never_produces_clean() -> None:
    scanner = resolve_scanner(settings())
    assert isinstance(scanner, UnavailableScanner)
    result = await scanner.scan(blocks(b"anything"))
    assert result.outcome is ScanOutcome.MISCONFIGURED
    assert not result.candidate_clean
    assert result.disposition is Disposition.HOLD_RETRY
    assert await scanner.ping() is False


def test_clamd_resolves_to_the_operators_host_and_the_configured_limits() -> None:
    scanner = resolve_scanner(
        settings(
            file_scan_backend="clamd",
            file_scan_clamd_host="scanner.internal",
            file_scan_clamd_port=3311,
            file_scan_connect_timeout_seconds=3,
            file_scan_timeout_seconds=60,
            file_scan_max_bytes=1024,
        ),
    )
    assert scanner == ClamdScanner("scanner.internal", 3311, 3, 60, 1024)


def test_the_host_is_the_operators_and_surrounding_blanks_are_not_part_of_it() -> None:
    cfg = settings(file_scan_backend="clamd", file_scan_clamd_host="  scanner.internal ")
    expected = ClamdScanner("scanner.internal", 3310, 5.0, 120.0, MAX_SCAN_BYTES)
    assert resolve_scanner(cfg) == expected


@pytest.mark.parametrize("host", ["", "   "])
async def test_clamd_with_no_host_is_an_unavailable_scanner_never_a_default(host: str) -> None:
    scanner = resolve_scanner(settings(file_scan_backend="clamd", file_scan_clamd_host=host))
    assert isinstance(scanner, UnavailableScanner)
    assert (await scanner.scan(blocks(b"x"))).outcome is ScanOutcome.MISCONFIGURED
    assert await scanner.ping() is False


def test_nothing_a_request_a_tenant_or_a_file_can_say_reaches_the_address() -> None:
    # The address is two settings the operator holds. Nothing in the package builds one from a
    # row, a key, a job payload or a header.
    joined = " ".join(sources().values())
    assert "os.environ" not in joined and "getenv" not in joined
    fields = ScannerSettings.model_fields
    assert {"file_scan_clamd_host", "file_scan_clamd_port"} <= set(fields)


@pytest.mark.parametrize(
    "values",
    [
        {"file_scan_clamd_port": 0},
        {"file_scan_clamd_port": 70000},
        {"file_scan_connect_timeout_seconds": 0},
        {"file_scan_connect_timeout_seconds": -1},
        {"file_scan_timeout_seconds": 0},
        {"file_scan_timeout_seconds": 601},
        {"file_scan_connect_timeout_seconds": 30, "file_scan_timeout_seconds": 10},
        {"file_scan_max_bytes": 0},
        {"file_scan_max_bytes": 100 * 1024 * 1024 + 1},
    ],
)
def test_out_of_range_settings_are_refused(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        settings(**values)


def test_the_ceiling_can_be_lowered_and_never_raised_past_the_ratified_limit() -> None:
    assert settings(file_scan_max_bytes=1024).file_scan_max_bytes == 1024
    with pytest.raises(ValidationError):
        settings(file_scan_max_bytes=MAX_SCAN_BYTES + 1)


# --- no bypass, no secrets, no shelling out -----------------------------------


def sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in SCANNING_DIR.glob("*.py")}


def test_production_code_does_not_import_or_define_a_fake() -> None:
    for name, text in sources().items():
        assert "scanner_support" not in text, name
        assert not re.search(r"class\s+Fake", text), name
    assert "fake" not in ScannerSettings.model_fields["file_scan_backend"].annotation.__args__  # type: ignore[union-attr]


def test_the_package_does_not_shell_out_or_use_a_third_party_scanner_library() -> None:
    for name, text in sources().items():
        imports = "\n".join(
            line for line in text.splitlines() if re.match(r"\s*(import|from)\s", line)
        )
        for module in ("subprocess", "pyclamd", "clamd", "clamav", "shlex", "pexpect"):
            pattern = rf"^\s*(import|from)\s+{module}(\s|$|\.)"
            assert not re.search(pattern, imports, re.M), (name, module)
        assert "os.system" not in text and "create_subprocess" not in text, name


def test_the_package_reads_no_secret_and_makes_no_http_call() -> None:
    for name, text in sources().items():
        imports = "\n".join(
            line for line in text.splitlines() if re.match(r"\s*(import|from)\s", line)
        )
        for token in ("httpx", "requests", "urllib", "aiohttp", "os", "doppler"):
            assert not re.search(rf"\b{token}\b", imports), (name, token)
        assert "os.environ" not in text and "getenv" not in text, name
    # The settings take no credential at all.
    assert not [f for f in ScannerSettings.model_fields if re.search("key|secret|token|pass", f)]


def test_the_package_has_no_database_or_queue_dependency_and_storage_only_in_the_adapter() -> None:
    for name, text in sources().items():
        for token in ("sqlalchemy", "arq", "redis", "koras_queue", "scan_status"):
            # `transition.py` is the one module that writes `files`, and it
            # alone may name SQLAlchemy and the status column. Nothing else may.
            if name == "transition.py" and token in {"sqlalchemy", "scan_status"}:
                continue
            # `runtime.py` makes the one read of the file row the orchestration
            # needs, so it names SQLAlchemy and the column in that predicate. It
            # writes nothing; `test_scan_runtime.py` holds that statically.
            if name == "runtime.py" and token in {"sqlalchemy", "scan_status"}:
                continue
            assert token not in text, (name, token)
        # The object reader's one S3 adapter is the only module that
        # may name the vendored storage package (see test_scanner_object_reader).
        if name != "s3.py":
            assert "koras_storage" not in text, name


def test_the_scanner_foundation_is_registered_in_exactly_one_place() -> None:
    """Bound through `tasks/scan.py`, listed by `worker.py`, re-enqueued by the sweep. No other
    file."""
    worker = SCANNING_DIR.parent
    naming = set()
    for path in worker.rglob("*.py"):
        if SCANNING_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if (
            "koras_worker.scanning" in text
            or "from ..scanning" in text
            or "file.scan" in text
            or "scan_tasks" in text
        ):
            naming.add(path.relative_to(worker).as_posix())
    assert naming == {"tasks/scan.py", "worker.py", "tasks/scan_sweep.py"}
