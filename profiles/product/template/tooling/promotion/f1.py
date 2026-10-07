"""F1 promotion detector: every releasable file must carry verified-digest evidence.

**The condition.** `F1_UNVERIFIED_RELEASABLE_COUNT = 0` in the target environment's database.
A *releasable* row is exactly what the product releases, asked of the one rule
(`koras_api.core.file_release`: `RELEASABLE_SQL` for the statement, `releasable` for a row in
hand). Nothing here re-implements it; a row the SQL returns is checked again with the Python
spelling and a disagreement raises.

**Read-only by construction.** The module issues `begin transaction read only`, asserts
`current_setting('transaction_read_only') = 'on'` (a connection option does not reach the
server), runs SELECT statements only (`SQL_STATEMENTS`, scanned by a unit test) and ends with
`rollback`. It needs a role that bypasses row-level security (`rolsuper or rolbypassrls`, the
`DATABASE_ADMIN_URL`): under the application role every count would read zero and prove
nothing, so that is a FAIL, not a pass. Unknown is never a pass: a missing URL, an unreachable
database, a transaction that is not read-only, a missing table or column all FAIL. Zero rows
against a reachable, migrated database is a legitimate PASS with count 0.

**What evidence is accepted.** A key is *own final* when it has the shape the finalizer writes
(`tenants/<t>/<cat>/<file>/final/<generation>/<name>`, `upload_window.is_final_key`) for this
tenant AND this file. `/final/` in the path is never enough on its own.

- `verified_digest`. Own final key, `checksum_sha256` is 64 lower-case hex, and
  `checksum_verified_at` is not null. The only writers of a non-null `checksum_verified_at` are
  the upload finalizer's swap (after it found the incoming object carrying its own upload id as
  provenance, hashed the incoming bytes to the claim, copied, and hashed the final copy to the
  claim again) and a restore replacement (which hashed the bytes it wrote and read them back);
  both reset the scan state to `pending`, so a clean verdict follows the verification by
  construction. Where the row lets us tell (`scan_attempted_at`), a verdict older than the
  verification (beyond `CLOCK_SKEW`), or no verdict time at all, is `verdict_predates_verification`.
  A verified timestamp with a malformed claim is `missing_claim`.

Everything else is a failing class, and the count of releasable rows in those is the raw
unverified count:

| classification | meaning |
|---|---|
| `final_key_no_verified_digest` | the F1 class: own final key, no verified digest |
| `verdict_predates_verification` | verified, but the verdict is older than the verification |
| `missing_claim` | `checksum_verified_at` set with no well-formed claim (inconsistent) |
| `legacy_key_releasable` | a pre-finalization five-segment key is releasable |
| `incoming_key_releasable` | an `incoming` key is releasable (a client could write it) |
| `unrecognised_key_shape` | anything else, including a key naming another tenant or file |

**Not proven, by design.** `verified_digest` rests on `checksum_verified_at` having only those
writers; no bytes are re-hashed here. The detector reads the database, not the store.

**Dispositions** (`f1.dispositions` in `promotion.yaml`, `local/config/f1-dispositions.yaml` by
default) are an explicit, committed, auditable list of `tenant:file` ids with a reason and a
recorded date, honoured **only for `dev`**. A dispositioned row is reported as
`dispositioned_synthetic`; the raw count and the net count are both always shown. A disposition
applies only while the row is still releasable and still has the classification that was
recorded. Any entry for another environment, and any malformed entry, is an error that fails the
check in every environment. Nothing is ever mutated. The Starter ships the file empty: dispositions
are a product's own decisions and never Starter content.

**Output** names a tenant id, a file id and a classification per row; counts per classification;
never an object key or a file name, and never a connection string.
"""

# ruff: noqa: S608 - the f-strings splice module constants only, never input
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .adapters import AdapterError, Runner, SecretStore, build_adapters, default_runner
from .config import ConfigError, PromotionConfig, load_config
from .result import ENVIRONMENTS, Check, fail, ok

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "services" / "api"
if _API.is_dir() and str(_API) not in sys.path:
    sys.path.append(str(_API))

from koras_api.core.file_release import RELEASABLE_SQL, releasable  # noqa: E402
from koras_api.core.upload_window import (  # noqa: E402
    FINAL,
    INCOMING,
    is_final_key,
    is_incoming_key,
)

CHECK_ID: Final = "f1_unverified_releasable"

#: Tolerance between the database clock and a worker clock (row timestamps) when comparing two
#: times. Seconds-level skew must not turn good evidence into a failure, and a tampered ordering
#: is days or more.
CLOCK_SKEW: Final = dt.timedelta(seconds=60)

VERIFIED_DIGEST: Final = "verified_digest"
SAFE_CLASSES: Final = frozenset({VERIFIED_DIGEST})

FINAL_KEY_NO_VERIFIED_DIGEST: Final = "final_key_no_verified_digest"
VERDICT_PREDATES: Final = "verdict_predates_verification"
MISSING_CLAIM: Final = "missing_claim"
LEGACY_KEY_RELEASABLE: Final = "legacy_key_releasable"
INCOMING_KEY_RELEASABLE: Final = "incoming_key_releasable"
UNRECOGNISED_KEY_SHAPE: Final = "unrecognised_key_shape"
UNSAFE_CLASSES: Final = frozenset(
    {
        FINAL_KEY_NO_VERIFIED_DIGEST,
        VERDICT_PREDATES,
        MISSING_CLAIM,
        LEGACY_KEY_RELEASABLE,
        INCOMING_KEY_RELEASABLE,
        UNRECOGNISED_KEY_SHAPE,
    }
)
DISPOSITIONED: Final = "dispositioned_synthetic"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_URL = re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S+", re.IGNORECASE)

# --- SQL: SELECT only. `SQL_STATEMENTS` is what a unit test scans. -----------------------

_BEGIN_READ_ONLY: Final = "begin transaction read only"
_ROLLBACK: Final = "rollback"

_Q_GUARD: Final = (
    "select current_setting('transaction_read_only') as read_only, "
    " coalesce((select rolsuper or rolbypassrls from pg_roles where rolname = current_user), "
    "  false) as bypasses_rls"
)

_Q_SCHEMA: Final = (
    "select table_name, column_name from information_schema.columns "
    "where table_schema = 'public' "
    " and table_name in ('files', 'tenants')"
)

_Q_TOTALS: Final = (
    "select (select count(*) from public.tenants)::int as tenants_total, "
    " (select count(distinct tenant_id) from public.files)::int as tenants_with_files, "
    " (select count(*) from public.files)::int as files_total"
)

_Q_NOT_RELEASABLE: Final = (
    "select f.status, f.scan_status, count(*)::int as n from public.files f "
    f"where not coalesce({RELEASABLE_SQL}, false) group by f.status, f.scan_status"
)

_Q_RELEASABLE: Final = (
    "select f.tenant_id::text as tenant_id, f.id::text as file_id, f.storage_key, "
    " f.status, f.scan_status, f.scan_object_etag, f.checksum_sha256, f.checksum_verified_at, "
    " f.scan_attempted_at "
    f"from public.files f where {RELEASABLE_SQL} order by f.tenant_id, f.id"
)

SQL_STATEMENTS: Final[tuple[str, ...]] = (
    _Q_GUARD,
    _Q_SCHEMA,
    _Q_TOTALS,
    _Q_NOT_RELEASABLE,
    _Q_RELEASABLE,
)

REQUIRED_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "tenants": frozenset({"id"}),
    "files": frozenset(
        {
            "id",
            "tenant_id",
            "storage_key",
            "status",
            "scan_status",
            "scan_object_etag",
            "checksum_sha256",
            "checksum_verified_at",
            "scan_attempted_at",
        }
    ),
}

QueryRunner = Callable[[str], Sequence[Mapping[str, Any]]]


class F1Error(Exception):
    """The detector could not establish the answer. Always a FAIL; the text is safe to print."""


# --- model -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RowResult:
    """One releasable row. No key and no file name, by construction."""

    tenant_id: str
    file_id: str
    classification: str
    claim_present: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "file_id": self.file_id,
            "classification": self.classification,
            "claim_present": self.claim_present,
        }


@dataclass(frozen=True, slots=True)
class F1Report:
    rows: tuple[RowResult, ...]
    not_releasable_pending: int
    not_releasable_other: int
    tenants_total: int
    tenants_with_files: int
    files_total: int
    read_only_confirmed: bool = True

    @property
    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(r.classification for r in self.rows).items()))

    @property
    def unverified(self) -> tuple[RowResult, ...]:
        return tuple(r for r in self.rows if r.classification not in SAFE_CLASSES)

    @property
    def raw_unverified_count(self) -> int:
        return len(self.unverified)


@dataclass(frozen=True, slots=True)
class Disposition:
    env: str
    tenant_id: str
    file_id: str
    classification: str
    reason: str
    recorded: str

    @property
    def ref(self) -> str:
        return f"{self.tenant_id}:{self.file_id}"


@dataclass(frozen=True, slots=True)
class Dispositions:
    entries: tuple[Disposition, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


# --- classification ----------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _is_own_final_key(key: str, tenant_id: str, file_id: str) -> bool:
    """The finalizer's shape, for this tenant AND this file."""
    if not is_final_key(key):
        return False
    parts = key.split("/")
    return parts[1] == tenant_id and parts[3] == file_id


def _is_own_legacy_key(key: str, tenant_id: str, file_id: str) -> bool:
    """`tenants/<t>/<cat>/<file>/<name>`: the shape before finalization existed."""
    parts = key.split("/")
    return (
        len(parts) == 5
        and "" not in parts
        and parts[0] == "tenants"
        and parts[1] == tenant_id
        and parts[3] == file_id
        and parts[3] not in (INCOMING, FINAL)
    )


def classify(row: Mapping[str, Any]) -> str:
    """The class of one releasable row; raises if it is not `ready` + `clean` (a caller bug)."""
    if row.get("status") != "ready" or row.get("scan_status") != "clean":
        raise F1Error("a row that is not releasable reached the classifier")
    tenant_id, file_id = str(row["tenant_id"]), str(row["file_id"])
    key = row.get("storage_key")
    if not isinstance(key, str) or not key:
        return UNRECOGNISED_KEY_SHAPE
    claim = row.get("checksum_sha256")
    well_formed = isinstance(claim, str) and bool(_SHA256.fullmatch(claim))
    verified_at = row.get("checksum_verified_at")

    if is_incoming_key(key):
        return INCOMING_KEY_RELEASABLE

    if _is_own_final_key(key, tenant_id, file_id):
        if verified_at is None:
            return FINAL_KEY_NO_VERIFIED_DIGEST
        if not well_formed:
            return MISSING_CLAIM
        verdict = row.get("scan_attempted_at")
        if not isinstance(verdict, dt.datetime) or (
            isinstance(verified_at, dt.datetime) and verdict < verified_at - CLOCK_SKEW
        ):
            # No verdict time at all cannot show the verdict followed the verification.
            return VERDICT_PREDATES
        return VERIFIED_DIGEST

    if _is_own_legacy_key(key, tenant_id, file_id):
        return LEGACY_KEY_RELEASABLE
    return UNRECOGNISED_KEY_SHAPE


def _rule_agrees(row: Mapping[str, Any]) -> bool:
    """The Python spelling of the release rule, asked of a row the SQL spelling returned."""
    return bool(
        releasable(
            status=row.get("status"),
            scan_status=row.get("scan_status"),
            tenant_id=str(row["tenant_id"]),
            row_tenant_id=str(row["tenant_id"]),
            storage_key=row.get("storage_key"),
            scan_object_etag=row.get("scan_object_etag"),
        )
    )


# --- detection (pure over an injected runner) ---------------------------------------------


def detect(run: QueryRunner) -> F1Report:
    """Classify every releasable row. `run(sql)` returns rows as mappings; it must be read-only."""
    guard = run(_Q_GUARD)
    if len(guard) != 1 or guard[0].get("read_only") != "on":
        raise F1Error("the transaction is not read-only; refusing to continue")
    if guard[0].get("bypasses_rls") is not True:
        raise F1Error(
            "the connecting role does not bypass row-level security, so a count would prove "
            "nothing; use the database admin URL"
        )

    present: dict[str, set[str]] = {}
    for found in run(_Q_SCHEMA):
        present.setdefault(str(found["table_name"]), set()).add(str(found["column_name"]))
    if not present:
        raise F1Error("the schema is empty: none of the expected tables exist")
    for table, columns in REQUIRED_COLUMNS.items():
        missing = columns - present.get(table, set())
        if table not in present:
            raise F1Error(f"the table {table} does not exist (database not migrated)")
        if missing:
            raise F1Error(f"the table {table} lacks columns: {', '.join(sorted(missing))}")

    totals = run(_Q_TOTALS)
    if len(totals) != 1:
        raise F1Error("the totals query did not return one row")
    pending = other = 0
    for group in run(_Q_NOT_RELEASABLE):
        if group["status"] == "ready" and group["scan_status"] == "clean":
            # `ready` + `clean` that is not releasable is an identity failure (a key that is not
            # the tenant's own final key, or no scanner stamp): withheld, and worth a look.
            other += int(group["n"])
        elif group["scan_status"] == "pending":
            pending += int(group["n"])
        else:
            other += int(group["n"])

    results: list[RowResult] = []
    for row in run(_Q_RELEASABLE):
        if not _rule_agrees(row):
            raise F1Error("the SQL and the Python spelling of the release rule disagree")
        claim = row.get("checksum_sha256")
        results.append(
            RowResult(
                tenant_id=str(row["tenant_id"]),
                file_id=str(row["file_id"]),
                classification=classify(row),
                claim_present=isinstance(claim, str) and bool(_SHA256.fullmatch(claim)),
            )
        )
    return F1Report(
        rows=tuple(results),
        not_releasable_pending=pending,
        not_releasable_other=other,
        tenants_total=int(totals[0]["tenants_total"]),
        tenants_with_files=int(totals[0]["tenants_with_files"]),
        files_total=int(totals[0]["files_total"]),
    )


# --- dispositions -------------------------------------------------------------------------


def load_dispositions(path: Path) -> Dispositions:
    """Read the committed list. A missing file is no dispositions; a malformed one is errors."""
    import yaml  # noqa: PLC0415

    if not path.is_file():
        return Dispositions()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        return Dispositions(
            errors=(f"the dispositions file cannot be read ({type(error).__name__})",)
        )
    if document is None:
        return Dispositions()
    if not isinstance(document, dict) or set(document) - {"version", "dispositions"}:
        return Dispositions(errors=("the dispositions file has an unexpected shape",))
    raw = document.get("dispositions") or []
    if not isinstance(raw, list):
        return Dispositions(errors=("`dispositions` must be a list",))
    entries: list[Disposition] = []
    errors: list[str] = []
    for index, item in enumerate(raw, start=1):
        label = f"entry {index}"
        if not isinstance(item, dict):
            errors.append(f"{label} is not a mapping")
            continue
        env = item.get("env")
        ref = item.get("ref")
        classification = item.get("classification")
        reason = item.get("reason")
        recorded = item.get("recorded")
        tenant, _, file_id = (ref if isinstance(ref, str) else "").partition(":")
        if env not in ENVIRONMENTS:
            errors.append(f"{label} names an unknown environment")
        elif env != "dev":
            errors.append(f"{label} is for {env}: dispositions are honoured for dev only")
        elif not (_is_uuid(tenant) and _is_uuid(file_id)):
            errors.append(f"{label} `ref` must be <tenant uuid>:<file uuid>")
        elif classification not in UNSAFE_CLASSES:
            errors.append(f"{label} `classification` must be a failing class")
        elif not isinstance(reason, str) or not reason.strip():
            errors.append(f"{label} needs a reason")
        elif not isinstance(recorded, dt.date):
            errors.append(f"{label} needs a `recorded` date")
        else:
            entries.append(
                Disposition(
                    env=str(env),
                    tenant_id=tenant,
                    file_id=file_id,
                    classification=str(classification),
                    reason=reason.strip(),
                    recorded=recorded.isoformat(),
                )
            )
    return Dispositions(entries=tuple(entries), errors=tuple(errors))


def check_f1(report: F1Report, env: str, dispositions: Dispositions) -> Check:
    """PASS only when the net unverified count is 0 and the dispositions file is clean."""
    if env not in ENVIRONMENTS:
        return fail(CHECK_ID, f"unknown environment {env!r}")
    applied: dict[str, Disposition] = {}
    ignored = 0
    if env == "dev":
        for item in dispositions.entries:
            applied[item.ref] = item
    else:
        ignored = len(dispositions.entries)

    unverified: list[dict[str, Any]] = []
    net = 0
    for row in report.unverified:
        entry = applied.get(f"{row.tenant_id}:{row.file_id}")
        covered = entry is not None and entry.classification == row.classification
        shown = row.as_dict()
        if covered:
            shown["disposition"] = DISPOSITIONED
            shown["recorded_classification"] = row.classification
        else:
            net += 1
        unverified.append(shown)
    current = {f"{r.tenant_id}:{r.file_id}": r.classification for r in report.unverified}
    stale = sorted(
        ref for ref, entry in applied.items() if current.get(ref) != entry.classification
    )
    raw = report.raw_unverified_count
    covered_count = raw - net
    counts = dict(report.counts)
    if covered_count:
        counts[DISPOSITIONED] = covered_count
    data: dict[str, Any] = {
        "env": env,
        "F1_UNVERIFIED_RELEASABLE_COUNT": net,
        "raw_unverified_count": raw,
        "dispositioned_count": covered_count,
        "counts": counts,
        "unverified_rows": unverified,
        "not_releasable_pending": report.not_releasable_pending,
        "not_releasable_other": report.not_releasable_other,
        "tenants_total": report.tenants_total,
        "tenants_with_files": report.tenants_with_files,
        "files_total": report.files_total,
        "releasable_total": len(report.rows),
        "dispositions_ignored": ignored,
        "dispositions_unmatched": stale,
        "disposition_errors": list(dispositions.errors),
        "read_only_confirmed": report.read_only_confirmed,
    }
    if dispositions.errors:
        return fail(
            CHECK_ID,
            f"{len(dispositions.errors)} invalid or non-dev disposition entr"
            f"{'y' if len(dispositions.errors) == 1 else 'ies'}; failing closed "
            f"(raw {raw}, net {net})",
            **data,
        )
    if net:
        return fail(
            CHECK_ID,
            f"{net} releasable file(s) have no verified-digest evidence in {env} "
            f"(raw {raw}, dispositioned {covered_count}, net {net})",
            **data,
        )
    return ok(
        CHECK_ID,
        f"every releasable file in {env} has evidence "
        f"(raw {raw}, dispositioned {covered_count}, net {net}; {len(report.rows)} releasable)",
        **data,
    )


# --- the real database --------------------------------------------------------------------


def redact(text: str, secret: str = "") -> str:
    cleaned = _URL.sub("<redacted-url>", text)
    return cleaned.replace(secret, "<redacted>") if secret else cleaned


def _dsn(url: str) -> str:
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", url, count=1)


def run_against_database(url: str) -> F1Report:
    """Open one connection, one read-only transaction, detect, roll back. Raises `F1Error`."""
    try:
        import asyncpg  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - asyncpg is a dependency of the API
        raise F1Error("asyncpg is not installed") from error
    loop = asyncio.new_event_loop()
    connection: Any = None
    try:
        try:
            connection = loop.run_until_complete(
                asyncpg.connect(_dsn(url), timeout=20, command_timeout=120, statement_cache_size=0)
            )
        except Exception as error:  # noqa: BLE001 - reported, redacted
            raise F1Error(f"the database is unreachable ({type(error).__name__})") from None
        loop.run_until_complete(connection.execute(_BEGIN_READ_ONLY))

        def run(sql: str) -> list[dict[str, Any]]:
            try:
                return [dict(r) for r in loop.run_until_complete(connection.fetch(sql))]
            except Exception as error:  # noqa: BLE001
                raise F1Error(f"a query failed ({type(error).__name__})") from None

        report = detect(run)
        loop.run_until_complete(connection.execute(_ROLLBACK))
        return report
    finally:
        if connection is not None:
            try:
                loop.run_until_complete(connection.close())
            except Exception:  # noqa: BLE001, S110
                pass
        loop.close()


def check_for_environment(
    env: str, config: PromotionConfig, store: SecretStore, *, url: str | None = None
) -> Check:
    """The detector against `env`'s own database, whose admin URL the secret store holds."""
    admin_url = url
    if admin_url is None:
        try:
            admin_url = store.get(env, config.database_admin_url_setting)
        except AdapterError as exc:
            return fail(CHECK_ID, f"{env}: {exc}")
    if not admin_url or not admin_url.strip():
        return fail(
            CHECK_ID,
            f"{env}: no {config.database_admin_url_setting} in the secret store; "
            "the environment has no database to inspect",
        )
    try:
        report = run_against_database(admin_url.strip())
        return check_f1(report, env, load_dispositions(config.f1_dispositions))
    except F1Error as exc:
        return fail(CHECK_ID, redact(str(exc), admin_url), env=env)


def main(argv: Sequence[str] | None = None, *, runner: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m promotion.f1", description="Read-only F1 promotion detector."
    )
    parser.add_argument("--env", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true", help="print the check as JSON only")
    parser.add_argument(
        "--allow-unbound",
        action="store_true",
        help="accept a database admin URL that the secret store's runner did not bind to --env",
    )
    args = parser.parse_args(argv)

    check: Check
    try:
        config = load_config(args.config)
        store, _ = build_adapters(config, runner)
    except (ConfigError, AdapterError) as exc:
        check = fail(CHECK_ID, str(exc), env=args.env)
    else:
        setting = config.database_admin_url_setting
        url = os.environ.get(setting, "").strip()
        bound = store.bound_environment(os.environ)
        if not args.allow_unbound and bound != args.env:
            check = fail(
                CHECK_ID,
                f"not running under the secret store's runner bound to {args.env} "
                f"({'unbound' if bound is None else 'bound to a different environment'}); the "
                f"database named by {setting} is never assumed to belong to --env "
                "(--allow-unbound overrides, knowingly)",
                env=args.env,
            )
        elif not url:
            check = fail(CHECK_ID, f"{setting} is not set; unknown is not a pass", env=args.env)
        else:
            check = check_for_environment(args.env, config, store, url=url)
    if args.json:
        print(  # noqa: T201
            json.dumps(
                {
                    "id": check.id,
                    "status": check.status,
                    "detail": check.detail,
                    "data": check.data,
                },
                indent=2,
                default=str,
            )
        )
    else:
        _print(check)
    return 0 if check.passed else 1


def _print(check: Check) -> None:
    print(f"{check.status} {check.id}: {check.detail}")  # noqa: T201
    data = check.data
    if "counts" not in data:
        return
    print(  # noqa: T201
        f"  F1_UNVERIFIED_RELEASABLE_COUNT = {data['F1_UNVERIFIED_RELEASABLE_COUNT']}"
        f" (raw {data['raw_unverified_count']}, dispositioned {data['dispositioned_count']})"
    )
    for name, n in data["counts"].items():
        print(f"  {name}: {n}")  # noqa: T201
    print(  # noqa: T201
        f"  not_releasable_pending: {data['not_releasable_pending']}"
        f" (non-failing); not_releasable_other: {data['not_releasable_other']}"
    )
    print(  # noqa: T201
        f"  tenants_total: {data['tenants_total']}, with files:"
        f" {data['tenants_with_files']}, files_total: {data['files_total']}"
    )
    for row in data["unverified_rows"]:
        marker = f" [{row['disposition']}]" if "disposition" in row else ""
        print(f"  row {row['tenant_id']} {row['file_id']} {row['classification']}{marker}")  # noqa: T201
    for message in data["disposition_errors"]:
        print(f"  disposition error: {message}")  # noqa: T201
    for ref in data["dispositions_unmatched"]:
        print(f"  disposition not matching any current row: {ref}")  # noqa: T201


if __name__ == "__main__":
    raise SystemExit(main())
