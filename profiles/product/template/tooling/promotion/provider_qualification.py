"""Executable object-store provider qualification (ADR 0013 sections 6 and 9).

The upload controls (signed copy-source preconditions, provenance metadata, a SHA-256 the worker
computes itself, immutable finalization) hold regardless of what a provider enforces. That is a
statement about one provider, one bucket and one date. This module turns it into a repeatable
qualification: the same attack matrix is run against the TARGET environment's own store, under
its own credentials, and the result is a record that vouches for exactly that store and exactly
this code.

Fail closed, everywhere:

* a required case that is missing, skipped, errored or failed is a FAIL; zero skips are tolerated;
* an environment without storage credentials is a FAIL, never a skip;
* a record vouches only for the storage fingerprint it was measured on, so one environment's
  record can never vouch for another's store;
* a record vouches only for the guard code it was measured against (`guard_hash`) and the
  harness it was measured with (`harness_version`), so a later change to the upload controls, to
  this module or to a suite invalidates it;
* a record is fresh for `max_age_days`, then stale.

The record holds no secret, no object key and no file name.

**The forged-provenance case (ADR 0013 section 9).** `m12_forged_nonempty_provenance` is the
harness's own regression for "provenance must equal the expected upload identity, not merely be
non-empty". It builds, with test-only mechanics and a disposable fixture, a copy-source ticket
that is intentionally left UNGUARDED (a provider that ignored the guard) and an object whose
copied provenance is forged and NON-EMPTY, and requires the real finalizer to refuse. Adding it
changed `HARNESS_VERSION`, the suite files (so `guard_hash`) and the set of required cases, so a
record issued before it is stale on three independent counts.

    python -m promotion.provider_qualification run    --env dev --junit out.xml --record out.json
    python -m promotion.provider_qualification verify --env dev --record out.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess  # noqa: S404 - runs the repository's own pytest, argument list, no shell
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .adapters import AdapterError, Runner, SecretStore, build_adapters, default_runner
from .config import REPO_ROOT, ConfigError, PromotionConfig, load_config
from .result import ENVIRONMENTS, Check, fail, ok


def _xml() -> Any:  # noqa: ANN401
    """`defusedxml` when it is installed, the standard parser otherwise.

    The junit file is the output of our own pytest run, never anything a tenant or a client wrote;
    the safer parser is still preferred wherever it exists.
    """
    try:
        return importlib.import_module("defusedxml.ElementTree")
    except ImportError:  # pragma: no cover
        return importlib.import_module("xml.etree.ElementTree")


CHECK_ID = "provider_qualification"
SCHEMA = 2
#: Bump when a case is added, removed or changes what it asserts. It is in the record and compared
#: on verification, in addition to `guard_hash` (which covers this file and the three suites, so
#: any such change moves it anyway). History: 1 = the attack matrix rows 1-11 and the download-URL
#: invariant; 2 = row 12, forged non-empty provenance on an unguarded copy-source ticket.
HARNESS_VERSION = 2
STORAGE_REQUIRED = (
    "STORAGE_ENDPOINT",
    "STORAGE_BUCKET",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
)
STORAGE_REGION_SETTING = "STORAGE_REGION"
DEFAULT_REGION = "us-east-1"  # what the suites assume when STORAGE_REGION is unset
CREDENTIAL_SOURCES = ("secret-store", "process")

CHECKSUM_SUITE = "tests/integration/test_upload_checksum_provider.py"
FINALIZE_SUITE = "tests/integration/test_upload_finalization_provider.py"
EXTRA_SUITE = "tests/integration/test_provider_qualification_extra.py"

#: The product files that implement the controls the matrix attacks, plus the suites that attack
#: them. A change to any of them invalidates every earlier record. `routers/files.py` is not
#: separable (the upload ticket is one function in a larger module), so it is included whole:
#: that errs toward re-qualifying, which is the safe direction.
GUARD_FILES: tuple[str, ...] = (
    "python-packages/koras-storage/src/koras_storage/__init__.py",
    "services/api/koras_api/core/upload_window.py",
    "services/api/koras_api/core/file_release.py",
    "services/api/koras_api/routers/files.py",
    "services/worker/koras_worker/uploads/finalize.py",
    "services/worker/koras_worker/tasks/finalize.py",
    "tooling/promotion/provider_qualification.py",
    CHECKSUM_SUITE,
    FINALIZE_SUITE,
    EXTRA_SUITE,
)

_INJECTED = (
    "acl",
    "all-at-once",
    "checksum-algorithm",
    "copy-range",
    "forged-provenance",
    "if-modified-since",
    "if-none-match",
    "metadata-replace",
    "second-if-match",
    "storage-class",
    "tagging-replace",
)
_FIN_IN_FLIGHT = "test_a_put_in_flight_past_the_ticket_expiry_cannot_alter_the_final_object"
_FIN_FINAL_KEY = "test_a_client_cannot_put_to_the_final_key_with_the_ticket_it_holds_or_with_none"


@dataclass(frozen=True, slots=True)
class Node:
    """One pytest function in one file; `params` are the parametrize ids that must all run."""

    file: str
    function: str
    params: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.file}::{self.function}"

    @property
    def junit_names(self) -> tuple[str, ...]:
        if self.params:
            return tuple(f"{self.function}[{p}]" for p in self.params)
        return (self.function,)


def _n(file: str, function: str, params: tuple[str, ...] = ()) -> Node:
    return Node(file, function, params)


_A = _n(
    CHECKSUM_SUITE,
    "test_A_an_ordinary_upload_with_the_correct_checksum_is_promoted_and_job",
)
_B = _n(
    CHECKSUM_SUITE, "test_B_a_wrong_checksum_is_withheld_whether_or_not_the_provider_enforces_it"
)
_C = _n(CHECKSUM_SUITE, "test_C_a_copy_from_a_victim_with_the_attackers_own_checksum_is_withheld")
_D = _n(
    CHECKSUM_SUITE,
    "test_D_a_copy_from_a_victim_with_the_victims_own_checksum_never_becomes_releasable",
)
_E = _n(CHECKSUM_SUITE, "test_E_an_altered_body_of_the_same_length_is_withheld")
_I = _n(
    CHECKSUM_SUITE,
    "test_I_unsigned_provider_headers_cannot_turn_a_guarded_put_into_a_copy",
    _INJECTED,
)
_I_DROPPED = _n(CHECKSUM_SUITE, "test_I_dropping_the_signed_guard_headers_is_refused")
_I_ORDINARY = _n(
    CHECKSUM_SUITE,
    "test_I_a_guarded_ticket_still_accepts_the_ordinary_upload_with_every_header_sent",
)
_F = _n(FINALIZE_SUITE, _FIN_IN_FLIGHT)
_GH = _n(FINALIZE_SUITE, _FIN_FINAL_KEY)
_Q04 = _n(EXTRA_SUITE, "test_Q04_an_unsigned_copy_source_header_never_lands_another_tenants_bytes")
_Q12A = _n(
    EXTRA_SUITE,
    "test_Q12a_the_download_url_as_a_copy_source_on_a_guarded_ticket_lands_nothing",
)
_Q12B = _n(
    EXTRA_SUITE,
    "test_Q12b_the_download_url_on_an_unguarded_ticket_is_held_for_want_of_provenance",
)
_Q12C = _n(
    EXTRA_SUITE,
    "test_Q12c_the_download_signature_cannot_write_delete_or_be_re_aimed",
)
_Q12D = _n(
    EXTRA_SUITE,
    "test_Q12d_a_download_url_gives_no_object_the_attacker_may_release_other_than_by_uploading",
)
#: ADR 0013 section 9: provenance must EQUAL the expected upload identity, not merely be non-empty.
_Q13 = _n(
    EXTRA_SUITE,
    "test_Q13_a_forged_nonempty_provenance_on_an_unguarded_copy_source_ticket_is_refused",
)

#: slug -> (matrix rows it answers, the tests that must all pass). Stable: a record names these.
REQUIRED_CASES: dict[str, tuple[tuple[str, ...], tuple[Node, ...]]] = {
    "m01_correct_checksum_upload": (("1",), (_A,)),
    "m02_wrong_checksum": (("2",), (_B,)),
    "m03_changed_same_length_body": (("3",), (_E,)),
    "m04_unsigned_copy_source": (("4",), (_Q04, _C)),
    "m05_copy_source_attacker_checksum": (("5",), (_C,)),
    "m06_copy_source_victim_checksum": (("6",), (_D,)),
    "m07_provenance_metadata": (("7",), (_A, _D, _I_DROPPED)),
    "m08_delayed_in_flight_put": (("8",), (_F,)),
    "m09_reaimed_put_to_final": (("9",), (_GH,)),
    "m10_unsigned_put_to_final": (("10",), (_GH,)),
    "m11_unsigned_header_injection": (("11",), (_I, _I_DROPPED, _I_ORDINARY)),
    "m12_forged_nonempty_provenance": (("12",), (_Q13,)),
    "inv_download_url_possession": (
        ("invariant",),
        (_Q12A, _Q12B, _Q12C, _Q12D),
    ),
}

Outcome = str  # passed | failed | skipped | error | missing


def required_nodes() -> list[Node]:
    """Every distinct test the qualification runs, in a stable order."""
    seen: dict[str, Node] = {}
    for _matrix, nodes in REQUIRED_CASES.values():
        for node in nodes:
            seen.setdefault(node.label, node)
    return list(seen.values())


# --- junit ---------------------------------------------------------------------------------------


def parse_junit(xml_text: str) -> dict[str, Outcome]:
    """`{"<file-stem>::<test name>": outcome}` for every testcase in a pytest junit file."""
    root = _xml().fromstring(xml_text)
    out: dict[str, Outcome] = {}
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        stem = classname.rsplit(".", 1)[-1] if classname else ""
        name = case.get("name", "")
        outcome: Outcome = "passed"
        if case.find("skipped") is not None:
            outcome = "skipped"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("failure") is not None:
            outcome = "failed"
        out[f"{stem}::{name}"] = outcome
    return out


def _stem(file: str) -> str:
    return Path(file).stem


def evaluate(results: Mapping[str, Outcome]) -> dict[str, Any]:
    """Case outcomes plus totals. A node's outcome is the worst of its parametrized variants."""
    rank = {"passed": 0, "skipped": 1, "failed": 2, "error": 3, "missing": 4}
    node_outcome: dict[str, Outcome] = {}
    consumed: set[str] = set()
    for node in required_nodes():
        worst: Outcome = "passed"
        for name in node.junit_names:
            key = f"{_stem(node.file)}::{name}"
            consumed.add(key)
            got = results.get(key, "missing")
            if rank[got] > rank[worst]:
                worst = got
        node_outcome[node.label] = worst
    cases: dict[str, Any] = {}
    for slug, (matrix, nodes) in REQUIRED_CASES.items():
        outcomes = {n.label: node_outcome[n.label] for n in nodes}
        status = max(outcomes.values(), key=lambda o: rank[o])
        cases[slug] = {"matrix": list(matrix), "status": status, "tests": outcomes}
    extras = {k: v for k, v in results.items() if k not in consumed}
    extra_bad = {k: v for k, v in extras.items() if v != "passed"}
    totals = {
        "passed": sum(1 for v in results.values() if v == "passed"),
        "failed": sum(1 for v in results.values() if v in {"failed", "error"}),
        "skipped": sum(1 for v in results.values() if v == "skipped"),
        "missing": sum(1 for v in node_outcome.values() if v == "missing"),
        "tests": len(results),
    }
    return {"cases": cases, "totals": totals, "extra_not_passed": sorted(extra_bad)}


def evaluate_check(results: Mapping[str, Outcome]) -> Check:
    """PASS only if every required case passed, nothing was skipped and nothing extra misbehaved."""
    report = evaluate(results)
    bad = {slug: c["status"] for slug, c in report["cases"].items() if c["status"] != "passed"}
    totals = report["totals"]
    if not results:
        return fail(CHECK_ID, "the junit file holds no test results", **totals)
    if bad:
        return fail(
            CHECK_ID,
            "required case(s) not passed: " + ", ".join(f"{s}={o}" for s, o in sorted(bad.items())),
            cases=bad,
            **totals,
        )
    if totals["skipped"] or report["extra_not_passed"]:
        return fail(
            CHECK_ID,
            f"{totals['skipped']} skipped and {len(report['extra_not_passed'])} unexpected "
            "non-passing test(s); zero skips are tolerated",
            extra=report["extra_not_passed"],
            **totals,
        )
    return ok(CHECK_ID, f"all {len(REQUIRED_CASES)} required cases passed", **totals)


# --- the stable identity of what was measured ---------------------------------------------------


def storage_fingerprint(endpoint: str, bucket: str, region: str | None) -> str:
    """sha256 of `endpoint|bucket|region`, full hex; names the store, reveals no credential."""
    material = f"{endpoint.strip()}|{bucket.strip()}|{(region or DEFAULT_REGION).strip()}"
    return hashlib.sha256(material.encode()).hexdigest()


def provider_name(endpoint: str) -> str:
    host = endpoint.lower()
    if "supabase" in host:
        return "supabase"
    if "r2.cloudflarestorage.com" in host:
        return "cloudflare-r2"
    if "amazonaws.com" in host:
        return "aws-s3"
    return "s3-compatible"


def compute_guard_hash(root: Path = REPO_ROOT, files: Sequence[str] = GUARD_FILES) -> str:
    """sha256 over the (line-ending-normalised) contents of the guard files, names included."""
    digest = hashlib.sha256()
    for rel in sorted(files):
        data = (root / rel).read_bytes().replace(b"\r\n", b"\n")
        digest.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def current_storage_fingerprint(env: str, store: SecretStore) -> str | None:
    """The fingerprint of `env`'s CURRENT storage config in the secret store, or None.

    Read-only. None when the store does not hold the endpoint and the bucket, or cannot be read:
    an environment with no storage configuration cannot be vouched for.
    """
    try:
        endpoint = store.get(env, "STORAGE_ENDPOINT")
        bucket = store.get(env, "STORAGE_BUCKET")
        region = store.get(env, STORAGE_REGION_SETTING)
    except AdapterError:
        return None
    if not endpoint or not endpoint.strip() or not bucket or not bucket.strip():
        return None
    return storage_fingerprint(endpoint, bucket, region.strip() if region else None)


def _git_commit() -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return proc.stdout.strip() or "unknown"


# --- the record ----------------------------------------------------------------------------------


def build_record(  # noqa: PLR0913
    *,
    env: str,
    results: Mapping[str, Outcome],
    fingerprint: str,
    guard_hash: str,
    provider: str,
    commit: str,
    now: datetime,
    duration_seconds: float,
    credentials_source: str = "secret-store",
) -> dict[str, Any]:
    report = evaluate(results)
    verdict = evaluate_check(results)
    return {
        "schema": SCHEMA,
        "harness_version": HARNESS_VERSION,
        "environment": env,
        "created_at": now.astimezone(UTC).isoformat(),
        "commit": commit,
        "provider": provider,
        "credentials_source": credentials_source,
        "storage_fingerprint": fingerprint,
        "guard_hash": guard_hash,
        "guard_files": list(GUARD_FILES),
        "duration_seconds": round(duration_seconds, 1),
        "totals": report["totals"],
        "cases": report["cases"],
        "extra_not_passed": report["extra_not_passed"],
        "result": verdict.status,
    }


def verify_record(  # noqa: PLR0911, PLR0913
    record: Mapping[str, Any] | None,
    env: str,
    current_fingerprint: str | None,
    current_guard: str | None,
    now: datetime,
    max_age_days: int = 14,
) -> Check:
    """PASS only when the record vouches for THIS store and THIS code, freshly, nothing skipped."""
    if env not in ENVIRONMENTS:
        return fail(CHECK_ID, f"unknown environment {env!r}")
    if not isinstance(record, Mapping) or record.get("schema") != SCHEMA:
        return fail(CHECK_ID, "no readable qualification record of the expected schema")
    if record.get("harness_version") != HARNESS_VERSION:
        return fail(
            CHECK_ID,
            "the record was measured with a different qualification harness "
            f"(record {record.get('harness_version')!r}, current {HARNESS_VERSION})",
        )
    if record.get("environment") != env:
        return fail(CHECK_ID, f"the record is for {record.get('environment')!r}, not {env!r}")
    if not current_fingerprint:
        return fail(CHECK_ID, f"{env} has no storage configuration to compare the record against")
    if record.get("storage_fingerprint") != current_fingerprint:
        return fail(
            CHECK_ID, f"the record was measured on a different store than {env}'s current one"
        )
    if not current_guard or record.get("guard_hash") != current_guard:
        return fail(CHECK_ID, "the upload-control code changed since this record was measured")
    try:
        created = datetime.fromisoformat(str(record["created_at"]))
    except (KeyError, ValueError):
        return fail(CHECK_ID, "the record has no valid timestamp")
    if created.tzinfo is None:
        return fail(CHECK_ID, "the record timestamp has no timezone")
    if created > now + timedelta(minutes=5):
        return fail(CHECK_ID, "the record is dated in the future")
    age = now - created
    if age > timedelta(days=max_age_days):
        return fail(CHECK_ID, f"the record is stale ({age.days} days old, limit {max_age_days})")
    cases = record.get("cases")
    if not isinstance(cases, Mapping) or set(cases) != set(REQUIRED_CASES):
        return fail(CHECK_ID, "the record's cases are not exactly the required qualification cases")
    bad = {
        s: (c.get("status") if isinstance(c, Mapping) else None)
        for s, c in cases.items()
        if not isinstance(c, Mapping) or c.get("status") != "passed"
    }
    if bad:
        return fail(CHECK_ID, "case(s) not passed: " + ", ".join(sorted(bad)), cases=bad)
    totals = record.get("totals") or {}
    if not isinstance(totals, Mapping) or (
        totals.get("skipped") or totals.get("failed") or totals.get("missing")
    ):
        return fail(CHECK_ID, "the record reports skipped, failed or missing tests")
    if record.get("result") != "PASS" or record.get("extra_not_passed"):
        return fail(CHECK_ID, "the record's own verdict is not PASS")
    return ok(
        CHECK_ID,
        f"{env} store qualified at {str(record.get('commit', '?'))[:12]} ({age.days} day(s) ago)",
        provider=record.get("provider"),
        **dict(totals),
    )


# --- running it ----------------------------------------------------------------------------------


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_url(url: str) -> bool:
    """True only when the URL's real host (after any userinfo) is a loopback name."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host is not None and host.lower() in LOOPBACK_HOSTS


def environment_check(env: str, environ: Mapping[str, str]) -> Check | None:
    """A FAIL when `environ` is not set up to qualify `env`'s store; None when it is.

    `environ` is the complete environment the pytest run gets: the target store's STORAGE_*
    settings and the disposable local database.
    """
    if env not in ENVIRONMENTS:
        return fail(CHECK_ID, f"unknown environment {env!r}")
    missing = [n for n in STORAGE_REQUIRED if not environ.get(n)]
    if missing:
        return fail(
            CHECK_ID,
            f"{env} has no storage credentials ({', '.join(missing)}); not skipped",
            missing=missing,
        )
    database = environ.get("E2E_DATABASE_URL")
    if not database:
        return fail(
            CHECK_ID,
            "E2E_DATABASE_URL is not set: it must name a disposable local Postgres",
        )
    if not _is_loopback_url(database):
        return fail(
            CHECK_ID,
            "E2E_DATABASE_URL does not name a loopback host (127.0.0.1, localhost or ::1); "
            "only a disposable local database is allowed",
        )
    return None


def storage_environ(
    env: str, store: SecretStore, process: Mapping[str, str], source: str
) -> dict[str, str] | Check:
    """The STORAGE_* settings the run uses, from the environment's own secret-store config
    (`secret-store`, the default) or from the process (`process`, an explicit choice)."""
    if source not in CREDENTIAL_SOURCES:
        return fail(CHECK_ID, f"unknown credentials source {source!r}")
    out = dict(process)
    if source == "process":
        return out
    for name in (*STORAGE_REQUIRED, STORAGE_REGION_SETTING):
        try:
            value = store.get(env, name)
        except AdapterError as exc:
            return fail(CHECK_ID, f"{env}: {exc}")
        if value and value.strip():
            out[name] = value.strip()
        else:
            out.pop(name, None)
    return out


def run(  # noqa: PLR0913
    env: str,
    junit_path: Path,
    record_path: Path | None = None,
    *,
    store: SecretStore,
    environ: Mapping[str, str] | None = None,
    source: str = "secret-store",
    now: datetime | None = None,
    python: str | None = None,
) -> Check:
    """Run the required tests under `env`'s storage settings and fail closed on any shortfall."""
    process = dict(os.environ if environ is None else environ)
    if record_path is not None:
        record_path.unlink(missing_ok=True)  # a stale PASS must not outlive any later run
    resolved = storage_environ(env, store, process, source)
    if isinstance(resolved, Check):
        return resolved
    blocked = environment_check(env, resolved)
    if blocked is not None:
        return blocked
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    if junit_path.exists():
        junit_path.unlink()
    command = [
        python or sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--no-cov",
        "-o",
        "addopts=",
        "-q",
        f"--junitxml={junit_path}",
        *[node.label for node in required_nodes()],
    ]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=REPO_ROOT, env=resolved, check=False)  # noqa: S603
    duration = time.monotonic() - started
    if not junit_path.exists():
        return fail(CHECK_ID, f"pytest produced no junit file (exit {proc.returncode})")
    results = parse_junit(junit_path.read_text(encoding="utf-8"))
    verdict = evaluate_check(results)
    if not verdict.passed:
        return verdict
    if proc.returncode != 0:
        return fail(
            CHECK_ID,
            f"pytest exited {proc.returncode} although the junit file reads clean",
            **verdict.data,
        )
    # Only a run that is clean in the junit file AND in its exit status leaves a record behind.
    if record_path is not None:
        record = build_record(
            env=env,
            results=results,
            fingerprint=storage_fingerprint(
                resolved["STORAGE_ENDPOINT"],
                resolved["STORAGE_BUCKET"],
                resolved.get(STORAGE_REGION_SETTING),
            ),
            guard_hash=compute_guard_hash(),
            provider=provider_name(resolved["STORAGE_ENDPOINT"]),
            commit=_git_commit(),
            now=now or datetime.now(UTC),
            duration_seconds=duration,
            credentials_source=source,
        )
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return verdict


def verify(
    env: str,
    record_path: Path,
    *,
    store: SecretStore,
    now: datetime | None = None,
    max_age_days: int = 14,
) -> Check:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    try:
        guard = compute_guard_hash()
    except OSError:
        guard = None
    return verify_record(
        record,
        env,
        current_storage_fingerprint(env, store),
        guard,
        now or datetime.now(UTC),
        max_age_days,
    )


def record_path_for(config: PromotionConfig, env: str) -> Path:
    return config.qualification_dir / f"{env}.json"


def main(argv: Sequence[str] | None = None, *, runner: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(prog="promotion.provider_qualification")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the attack matrix against the environment's own store")
    run_p.add_argument("--env", required=True, choices=ENVIRONMENTS)
    run_p.add_argument("--junit", required=True, type=Path)
    run_p.add_argument("--record", required=True, type=Path)
    run_p.add_argument(
        "--credentials",
        choices=CREDENTIAL_SOURCES,
        default="secret-store",
        help="where the target store's STORAGE_* settings come from; `process` is for a "
        "disposable local store and the record then verifies only against a store with the "
        "same fingerprint",
    )
    ver_p = sub.add_parser(
        "verify", help="check a record against the environment's current store and code"
    )
    ver_p.add_argument("--env", required=True, choices=ENVIRONMENTS)
    ver_p.add_argument("--record", required=True, type=Path)
    ver_p.add_argument("--max-age-days", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        store, _ = build_adapters(config, runner)
    except (ConfigError, AdapterError) as exc:
        print(f"FAIL {CHECK_ID}: {exc}")  # noqa: T201
        return 1
    if args.command == "run":
        check = run(args.env, args.junit, args.record, store=store, source=args.credentials)
    else:
        check = verify(
            args.env,
            args.record,
            store=store,
            max_age_days=args.max_age_days or config.qualification_max_age_days,
        )
    print(f"{check.status} {check.id}: {check.detail}")  # noqa: T201
    return 0 if check.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
