"""A workbook as rows, by the rules the CSV reader already keeps.

The point of this module is what it does *not* add: a second header rule, a
second row rule, a second idea of what a cell is. `header_from` and `row_from`
are the CSV reader's, so a spreadsheet saved as CSV and the same spreadsheet
saved as XLSX name their columns identically and produce the same cells. The
only thing a workbook has that a CSV does not is a typed cell, and `cell_text`
turns every one into the text the validator expects before anything sees it.

**Bounded three ways before a sheet is opened.** The caller has already
refused a file over the compressed ceiling. Here the zip directory is read and
the uncompressed sizes summed, and a file claiming more than
`DECOMPRESSED_CEILING` is refused without decompressing any of it -- a small
workbook can expand by two orders of magnitude, and IMP2-15 already said the
byte ceiling bounded the transfer rather than the memory. A workbook carrying
a macro project is refused, and one with no workbook part is not a workbook.

**Cells are read with their cached values.** A formula never runs; it
contributes whatever the spreadsheet last calculated, or nothing. A cell whose
first character is a formula trigger is data here and is guarded on the way
out, where it always was.
"""

from __future__ import annotations

import io
import math
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree  # noqa: S405 - bounded input, no entities resolved

from .compatibility import PROPERTY_NAME
from .reading import MAX_CELL, Header, ReadRefused, Row, header_from, row_from

#: Summed from the zip directory before any entry is opened. ADR 0012 D12.
DECOMPRESSED_CEILING = 256 * 1024 * 1024

#: The document-properties part is a few hundred bytes. One larger than this
#: is not read, so a hostile part cannot make the identity check expensive.
MAX_PROPERTY_BYTES = 64 * 1024

#: The sheet the template writes and the reader prefers. A workbook with no
#: sheet of that name is read from its first sheet, because most files a
#: customer has were not made from the template.
DATA_SHEET = "Data"

_WORKBOOK_PART = "xl/workbook.xml"
_MACRO_PART = "xl/vbaProject.bin"
_PROPERTIES_PART = "docProps/custom.xml"
_VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"


@dataclass(frozen=True)
class WorkbookRead:
    header: Header
    #: Up to `limit` rows, in order.
    rows: tuple[Row, ...]
    #: Rows seen while counting, stopping once past `ceiling`.
    rows_seen: int
    sheet: str
    #: The template identity the file carried, or None.
    identity: str | None


def inspect(raw: bytes) -> zipfile.ZipFile:
    """Refuse what is not a safe workbook before opening any of it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as broken:
        raise ReadRefused("the file is not a workbook") from broken
    names = set(archive.namelist())
    if _WORKBOOK_PART not in names:
        raise ReadRefused("the file is not a workbook")
    if _MACRO_PART in names:
        raise ReadRefused("a workbook with macros is not read; save it as .xlsx first")
    total = sum(info.file_size for info in archive.infolist())
    if total > DECOMPRESSED_CEILING:
        raise ReadRefused(
            f"this workbook would expand to {total} bytes, over the "
            f"{DECOMPRESSED_CEILING} limit"
        )
    return archive


def template_identity(archive: zipfile.ZipFile) -> str | None:
    """The identity property, read without opening the workbook itself."""
    try:
        info = archive.getinfo(_PROPERTIES_PART)
    except KeyError:
        return None
    if info.file_size > MAX_PROPERTY_BYTES:
        return None
    part = archive.read(_PROPERTIES_PART)
    # A properties part never declares a document type or an entity. One that
    # does is not read at all, which closes entity expansion before the
    # parser is reached rather than trusting the parser to bound it.
    if b"<!DOCTYPE" in part or b"<!ENTITY" in part:
        return None
    try:
        root = ElementTree.fromstring(part)  # noqa: S314 - bounded, entity-free
    except ElementTree.ParseError:
        return None
    for prop in root:
        if prop.get("name") != PROPERTY_NAME:
            continue
        for child in prop:
            if child.tag == f"{_VT}lpwstr" and child.text:
                return child.text.strip()
    return None


def cell_text(value: Any) -> str:  # noqa: ANN401 - whatever openpyxl handed over
    """A typed cell as the text the validator would have read from a CSV.

    - `None` is an empty cell.
    - A boolean is `true` or `false`, which the validator accepts.
    - An integral float is written without its `.0`, because a spreadsheet
      stores every number as a float and `42.0` is not a whole number to the
      integer check.
    - A non-finite float is written as its name, so the decimal check refuses
      it rather than this module deciding for it.
    - A date is ISO. A datetime at midnight is its date; one with a time of
      day keeps the time, so a date column refuses it and says so.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    text = str(value)
    if len(text) > MAX_CELL:
        raise ReadRefused(
            f"a cell is {len(text)} characters, over the {MAX_CELL} limit; "
            "this is a file in a cell rather than a value"
        )
    return text


def _trimmed(values: Sequence[Any]) -> list[str]:
    """Cells as text, with the trailing empties a workbook pads rows with removed."""
    cells = [cell_text(value) for value in values]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def read_workbook(raw: bytes, *, limit: int, ceiling: int) -> WorkbookRead:
    """The header, up to `limit` rows, and a count that stops past `ceiling`."""
    from openpyxl import load_workbook

    archive = inspect(raw)
    found = template_identity(archive)
    archive.close()

    try:
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as broken:  # noqa: BLE001 - openpyxl raises several types
        raise ReadRefused("the file could not be read as a workbook") from broken
    try:
        sheet = book[DATA_SHEET] if DATA_SHEET in book.sheetnames else book.worksheets[0]
        if hasattr(sheet, "reset_dimensions"):
            sheet.reset_dimensions()
        rows_iter = sheet.iter_rows(values_only=True)
        header: Header | None = None
        rows: list[Row] = []
        seen = 0
        number = 0
        for number, values in enumerate(rows_iter, start=1):
            cells = _trimmed(values)
            if header is None:
                if not cells:
                    raise ReadRefused("the file's first row names no columns")
                header = header_from(cells)
                continue
            if not any(cells):
                continue
            seen += 1
            if seen > ceiling:
                break
            if len(rows) < limit:
                rows.append(row_from(number, cells, header))
        if header is None:
            raise ReadRefused("the file is empty")
        return WorkbookRead(
            header=header,
            rows=tuple(rows),
            rows_seen=seen,
            sheet=sheet.title,
            identity=found,
        )
    finally:
        book.close()


__all__ = [
    "DATA_SHEET",
    "DECOMPRESSED_CEILING",
    "MAX_PROPERTY_BYTES",
    "WorkbookRead",
    "cell_text",
    "inspect",
    "read_workbook",
    "template_identity",
]
