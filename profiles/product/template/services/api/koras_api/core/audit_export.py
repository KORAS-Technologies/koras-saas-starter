"""Rendering audit rows as a file, and writing it where the tenant can fetch it.

Three formats, and each exists for a different reader: CSV for a spreadsheet,
JSON for a person opening it once, NDJSON for a pipeline that reads a line at a
time and should not hold the whole export in memory.

**Why this does not use `koras_reporting.export`.** That package renders
reports and is a capability dependency: the API declares it only when
`reporting` is generated. Audit is foundation, so an export route that imported
it would break in exactly the products that most need an audit trail and least
need analytics. The renderers below are forty lines; the coupling would have
been permanent.

Nothing here decides *who* may export. That is the route's job, and the answer
is in `routers/audit.py`.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime

logger = logging.getLogger(__name__)

#: The columns an export carries, in this order. `details` is rendered as JSON
#: in every format, because a details map has no fixed shape and flattening it
#: would give two exports different columns.
COLUMNS = (
    "id",
    "created_at",
    "action",
    "classification",
    "actor_id",
    "target_type",
    "target_id",
    "outcome",
    "details",
)

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "ndjson": "application/x-ndjson",
}

#: How long an artifact stays fetchable. An export of audit records should not
#: sit in a bucket forever because somebody clicked once.
DEFAULT_EXPIRY_DAYS = 7


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping | list):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _record(row: object) -> dict[str, object]:
    return {name: getattr(row, name, None) for name in COLUMNS}


def render(rows: Iterable[object], fmt: str) -> bytes:
    """One export, as bytes. Raises `ValueError` for a format nobody offers."""
    if fmt not in MEDIA_TYPES:
        raise ValueError(f"unknown export format {fmt!r}")
    records = [_record(row) for row in rows]

    if fmt == "csv":
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({name: _cell(record[name]) for name in COLUMNS})
        # utf-8-sig: Excel reads a bare utf-8 CSV as the host codepage and
        # mangles every non-ASCII actor name. The BOM is the difference between
        # a file that opens correctly and a support ticket.
        return buffer.getvalue().encode("utf-8-sig")

    if fmt == "ndjson":
        lines = (
            json.dumps({name: _cell(record[name]) for name in COLUMNS}, sort_keys=True)
            for record in records
        )
        return ("\n".join(lines) + "\n").encode("utf-8") if records else b""

    return json.dumps(
        [{name: _cell(record[name]) for name in COLUMNS} for record in records],
        sort_keys=True,
        indent=2,
    ).encode("utf-8")


def filename(export_id: str, fmt: str) -> str:
    """A name a person can tell apart from the last one they downloaded."""
    return f"audit-{export_id[:8]}.{fmt}"
