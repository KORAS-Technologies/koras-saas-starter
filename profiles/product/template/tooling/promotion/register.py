"""The security register, parsed strictly (the gate's `security_findings` check).

The register is a Markdown table the product keeps (`register.path` in `promotion.yaml`). The gate
asks one question of it: is any Critical or High finding of a security type unresolved? Because the
answer gates a promotion, the parser is built so that a register it cannot read FAILS the check
rather than passing it:

* Columns come from the register's own header row (a row that names `id` and `type`). No header, no
  answer; a header without `id`, `type`, `severity` and `status` is an error.
* A data row is a table line whose first cell matches `register.id_pattern`. A row whose cell count
  differs from the header (typically a stray `|` inside a cell shifting the columns) and that
  mentions SECURITY, Critical or High anywhere is **unparseable**, and an unparseable row FAILS the
  check; it is never skipped. The one exception is a misshapen row whose Type cell (which precedes
  every free-text cell, so a stray `|` cannot move it) is an intact token outside the gated types:
  it cannot be a gated finding, whatever its other cells do.
* A finding is gated when its type is SECURITY or SECURITY-GAP and its severity starts with
  Critical or High (any case). It is resolved only when its Status cell holds RESOLVED, CLOSED,
  WITHDRAWN or SUPERSEDED as a whole upper-case word (the register's own style) not preceded within
  12 characters by NOT, UN, PART+IALLY (one word), TO BE, UNTIL or BLOCKED.
* A later row for the same id supersedes an earlier one.
* A register with a header and no rows is an error, because that is also what reading the wrong
  file looks like. A product with genuinely no findings says so with the explicit marker line
  `<!-- koras:register-empty -->`, which is honoured only when no row exists.

Design decision, carried from the implementation this was proven in: a finding resolved in one
environment counts as resolved. The fix is code, which is the same in every environment; the
controls that are NOT environment-independent (the provider's behaviour, the data already in an
environment, the activation state) have their own checks (provider qualification, F1, activation).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

EMPTY_MARKER: Final = "<!-- koras:register-empty -->"
GATED_TYPES: Final = frozenset({"SECURITY", "SECURITY-GAP"})
GATED_SEVERITY_PREFIXES: Final = ("critical", "high")
REQUIRED_COLUMNS: Final = ("id", "type", "severity", "status")

_RESOLVED_WORD = re.compile(r"\b(?:RESOLVED|CLOSED|WITHDRAWN|SUPERSEDED)\b")
_NEGATING = re.compile(
    r"(?<![A-Za-z])(?:NOT|UN|PART(?:IAL)LY|TO BE|UNTIL|BLOCKED)(?![A-Za-z])", re.I
)
_NEGATION_WINDOW = 12
_SENSITIVE_MENTION = re.compile(r"security|critical|high", re.I)
_TYPE_TOKEN = re.compile(r"[A-Z][A-Z-]*")


class RegisterError(Exception):
    """The register could not be read. Always a FAIL; the message is safe to print."""


def is_resolved(status: str) -> bool:
    for match in _RESOLVED_WORD.finditer(status):
        window = status[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
        if not _NEGATING.search(window):
            return True
    return False


def parse_register(text: str, id_pattern: str) -> tuple[dict[str, dict[str, str]], list[str], bool]:
    """`(rows by id, unparseable row labels, header seen)`."""
    ident = re.compile(id_pattern)
    rows: dict[str, dict[str, str]] = {}
    unparseable: list[str] = []
    columns: dict[str, int] | None = None
    width = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        is_row = len(cells) > 1 and bool(ident.fullmatch(cells[1].strip("* ")))
        if not is_row:
            lowered = [c.lower() for c in cells]
            if "id" in lowered and "type" in lowered:
                columns = {name: i for i, name in enumerate(lowered) if name}
                width = len(cells)
                if any(name not in columns for name in REQUIRED_COLUMNS):
                    raise RegisterError("the register header lacks a required column")
            continue
        if columns is None:
            raise RegisterError("a register row appears before any header row")
        if len(cells) != width:
            kind = cells[2].strip("* ").upper() if len(cells) > 2 else ""
            settled_elsewhere = bool(_TYPE_TOKEN.fullmatch(kind)) and kind not in GATED_TYPES
            if not settled_elsewhere and _SENSITIVE_MENTION.search(line):
                unparseable.append(cells[1] if len(cells) > 1 and cells[1] else f"line {number}")
            continue
        rows[cells[columns["id"]].strip("* ")] = {
            name: cells[columns[name]] for name in REQUIRED_COLUMNS
        }
    return rows, unparseable, columns is not None


def unresolved_security_findings(
    register: Path, id_pattern: str, chain_ids: frozenset[str] = frozenset()
) -> list[dict[str, str]]:
    try:
        text = register.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RegisterError("the security register could not be read") from exc
    rows, unparseable, header_seen = parse_register(text, id_pattern)
    if unparseable:
        raise RegisterError(
            f"{len(unparseable)} register row(s) could not be parsed and are not skipped: "
            + ", ".join(sorted(set(unparseable)))
        )
    if not header_seen:
        raise RegisterError("the security register has no header row")
    if not rows:
        if EMPTY_MARKER in text:
            return []
        raise RegisterError("the security register held no rows")
    found = []
    for rid, row in rows.items():
        kind = row["type"].strip("* ").upper()
        severity = row["severity"].strip("* ")
        if (
            kind in GATED_TYPES
            and severity.lower().startswith(GATED_SEVERITY_PREFIXES)
            and not is_resolved(row["status"])
        ):
            found.append(
                {
                    "id": rid,
                    "severity": severity,
                    "scope": "chain" if rid in chain_ids else "other",
                }
            )
    return sorted(found, key=lambda r: r["id"])
