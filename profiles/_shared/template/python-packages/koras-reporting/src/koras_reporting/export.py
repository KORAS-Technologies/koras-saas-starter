"""A report as a file.

CSV, through the standard library's writer, with one defence a writer does
not give: a cell that begins with a character a spreadsheet reads as a
formula is prefixed with an apostrophe, so a tenant's own data -- a file
named `=HYPERLINK(...)`, a member called `+1` -- opens as text and executes
nothing on the machine of whoever downloaded it.

Bounded. A result with more rows than `EXPORT_ROW_LIMIT` is refused by the
caller before it gets here; this writes what it is given.
"""

from __future__ import annotations

import csv
import io

from .results import Cell, ReportResult

#: The most rows one synchronous export carries. Past this the answer is
#: "narrow the range", and the asynchronous export is the follow-up.
EXPORT_ROW_LIMIT = 10_000

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # A count that travelled as a float is still a count on paper.
        value = int(value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def to_csv(result: ReportResult) -> str:
    """The rows of the report's table, or its metrics when it has no table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if result.table is not None and result.table.columns:
        writer.writerow([_cell(column.label) for column in result.table.columns])
        for row in result.table.rows:
            writer.writerow([_cell(row.get(column.key)) for column in result.table.columns])
        return buffer.getvalue()
    writer.writerow(["metric", "value", "unit", "kind"])
    for metric in result.metrics:
        writer.writerow([_cell(metric.label), _cell(metric.value), metric.unit.value, metric.kind])
    return buffer.getvalue()


def export_filename(key: str, start: str | None, end: str | None) -> str:
    stem = key.replace(".", "-")
    if start and end:
        return f"{stem}-{start}-to-{end}.csv"
    return f"{stem}.csv"
