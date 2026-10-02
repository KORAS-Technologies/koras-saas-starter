"""Which column is which, and whether the rows under them are acceptable.

Two jobs that belong together because they fail together: a mapping is only
right if the values under it validate, and a validation error is only
actionable if it names the column the person is looking at rather than the
field the product calls it.

**Every problem in one pass.** A validator that stopped at the first bad row
would make fixing a hundred-row file a hundred attempts. So validation collects
every error in every row, bounded by a reported-error ceiling, and the run
reports all of them at once.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from .reading import Row
from .targets import FieldKind, FieldSpec, ImportTarget

#: Deliberately permissive. A stricter pattern refuses addresses that exist,
#: and the only authority on whether an address works is sending to it — which
#: an import does not do.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

#: What a spreadsheet writes when it means yes or no, in the three languages
#: this platform speaks plus the shapes a database export produces.
_TRUE = frozenset({"true", "t", "yes", "y", "1", "ja", "j", "si", "sí", "wahr"})
_FALSE = frozenset({"false", "f", "no", "n", "0", "nein", "falsch"})
_BOOLEANS = _TRUE | _FALSE

#: Tried in order. ISO first because it is unambiguous; the other two because a
#: spreadsheet writes them and refusing every file that contains one would
#: refuse most real files. **There is no `%m/%d/%Y`**: it is indistinguishable
#: from `%d/%m/%Y` for the first twelve days of a month, and a date that is
#: silently wrong eleven times in twelve is worse than a date that is refused.
_DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y")

#: Beyond this the report stops being a list of problems and starts being a
#: second copy of the file. The run records that it was truncated.
MAX_REPORTED_ERRORS = 1000


class MappingRefused(ValueError):
    """The mapping cannot be used against this target and this file."""


@dataclass(frozen=True)
class ResolvedMapping:
    """A mapping checked against both the target and the file."""

    #: Source column name → target field name.
    columns: dict[str, str]
    #: Columns in the file that the mapping ignores. Not an error: a real
    #: export carries columns the product has no field for.
    unmapped_columns: tuple[str, ...]

    @property
    def fields(self) -> dict[str, str]:
        """Target field → source column. The direction validation reads."""
        return {field: column for column, field in self.columns.items()}


def _normalise(name: str) -> str:
    """A column name reduced to what two people would agree it means."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def suggest(target: ImportTarget, columns: Iterable[str]) -> dict[str, str]:
    """A mapping to offer a person before they touch anything.

    Matches on the name with punctuation, spacing and case removed, so
    `E-Mail Address`, `email_address` and `EmailAddress` all find the same
    field. Suggests nothing it is unsure about: this is a starting point a
    person corrects, and a confident wrong guess costs more than a blank.

    Ambiguity resolves to nothing. Two columns normalising to the same field
    means the person has to say which, because picking the first would depend
    on column order.
    """
    by_field = {_normalise(name): name for name in target.field_names}
    found: dict[str, str] = {}
    claimed: dict[str, int] = {}
    for column in columns:
        field = by_field.get(_normalise(column))
        if field is None:
            continue
        claimed[field] = claimed.get(field, 0) + 1
        found[column] = field
    contested = {field for field, count in claimed.items() if count > 1}
    return {
        column: field for column, field in found.items() if field not in contested
    }


def resolve(
    target: ImportTarget,
    columns: Iterable[str],
    mapping: Mapping[str, str],
    *,
    require_match_keys: bool = False,
) -> ResolvedMapping:
    """Check a browser-supplied mapping against the target and the file.

    **This is the allowlist, and it refuses rather than ignores.** A mapping
    naming a field the target did not declare is not dropped quietly — dropping
    it is how an import writes a column it was never meant to reach, and how a
    caller learns nothing about why their data did not arrive.
    """
    available = tuple(columns)
    known = set(available)
    fields = set(target.field_names)

    unknown_fields = sorted(set(mapping.values()) - fields)
    if unknown_fields:
        raise MappingRefused(
            f"target {target.key} does not accept {unknown_fields}; it accepts "
            f"{sorted(fields)}"
        )

    unknown_columns = sorted(set(mapping) - known)
    if unknown_columns:
        raise MappingRefused(
            f"the file has no column called {unknown_columns}"
        )

    assigned = list(mapping.values())
    twice = sorted({field for field in assigned if assigned.count(field) > 1})
    if twice:
        raise MappingRefused(
            f"{twice} is mapped from more than one column; a field takes one"
        )

    missing = sorted(set(target.required_fields) - set(assigned))
    if missing:
        # Named, because "a required column is missing" without saying which is
        # the refusal a person cannot act on.
        raise MappingRefused(
            f"target {target.key} requires {missing}, and no column is mapped to "
            "them"
        )

    if require_match_keys:
        # An operation that has to recognise a row it has seen before cannot
        # do so through a mapping that omits the key it recognises by. Left
        # unmapped, duplicate detection silently switched itself off and the
        # writer met a constraint instead -- IMP2-20 in
        # `docs/features/data-import/phase-2-review.md`.
        unmapped_keys = sorted(set(target.match_keys) - set(assigned))
        if unmapped_keys:
            raise MappingRefused(
                f"target {target.key} recognises an existing record by "
                f"{unmapped_keys}, and no column is mapped to them; map them, or "
                "choose to add every row as new"
            )

    return ResolvedMapping(
        columns=dict(mapping),
        unmapped_columns=tuple(name for name in available if name not in mapping),
    )


@dataclass(frozen=True)
class RowError:
    """One problem, in the words of the file rather than of the schema."""

    #: 1-based including the header, matching the file's own left margin.
    row: int
    #: The **source** column, because that is what the person is looking at. An
    #: error naming `external_reference` when the spreadsheet says `Ref No` is
    #: an error about somebody else's file.
    column: str
    field: str
    #: An i18n code, resolved by the browser. Never a sentence: a sentence here
    #: is an English sentence in a German customer's error report.
    code: str
    #: The offending value, trimmed. Shown beside the message so a person can
    #: find the cell without counting columns.
    value: str = ""


@dataclass(frozen=True)
class Validation:
    rows: int
    valid: int
    errors: tuple[RowError, ...]
    #: True when more errors existed than the report carries.
    truncated: bool = False
    #: Rows the in-file duplicate check flagged. A figure of its own because
    #: the preview shows it beside the invalid count rather than inside it.
    duplicates: int = 0
    #: Every row with at least one problem, whether or not its problems made
    #: it into `errors` before the report was cut. The matcher needs the full
    #: set: a prediction over a row the report could not list is still wrong.
    bad_rows: frozenset[int] = frozenset()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class _Mapped:
    """One mapped field, with everything a row will be asked about it."""

    field: str
    column: str
    spec: FieldSpec
    #: The field's options lower-cased, or None when it declares none.
    options: frozenset[str] | None


@dataclass(frozen=True)
class _Plan:
    """A target and a mapping, looked up once instead of once a cell.

    `ResolvedMapping.fields` builds a dictionary every time it is read and
    `ImportTarget.spec` walks the field list, so asking both of every cell is
    work that grows with the square of the column count: GR-352C measured a
    3,900-row file of 256 mapped columns at 7 seconds of validation and 13 of
    preparation, almost all of it this. Nothing a row is told changes -- the
    same fields in the same order, the same specifications -- only how often
    the question is asked. IMPORT-DEF-015.
    """

    mapped: tuple[_Mapped, ...]
    #: The match keys: each one's specification and the column it is read
    #: from, which is `""` when the mapping leaves it out.
    keys: tuple[tuple[FieldSpec, str], ...]
    #: Target field to source column, built once. `resolved.fields`.
    fields: dict[str, str]


def _plan(target: ImportTarget, resolved: ResolvedMapping) -> _Plan:
    fields = resolved.fields
    mapped: list[_Mapped] = []
    for name, column in fields.items():
        spec = target.spec(name)
        mapped.append(
            _Mapped(
                field=name,
                column=column,
                spec=spec,
                options=(
                    frozenset(option.lower() for option in spec.options)
                    if spec.options
                    else None
                ),
            )
        )
    return _Plan(
        mapped=tuple(mapped),
        keys=tuple((target.spec(name), fields.get(name, "")) for name in target.match_keys),
        fields=fields,
    )


def validate_row(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> list[RowError]:
    """Every problem in one row. Never stops at the first."""
    return _problems(target, _plan(target, resolved), row)


def _problems(target: ImportTarget, plan: _Plan, row: Row) -> list[RowError]:
    problems: list[RowError] = []
    if row.long:
        problems.append(
            RowError(
                row=row.number,
                column="",
                field="",
                code="import.error.extra_cells",
            )
        )

    cells = row.cells
    for item in plan.mapped:
        value = cells.get(item.column, "").strip()
        code = _check(item.spec, value, item.options)
        if code is not None:
            problems.append(
                RowError(
                    row=row.number,
                    column=item.column,
                    field=item.field,
                    code=code,
                    value=value[:120],
                )
            )

    if problems or target.validator is None:
        # The product's own rules see a row that already passed the shape
        # checks, so a validator never has to re-check that a number is a
        # number — and never runs against a row it would only report twice.
        return problems

    mapped = {item.field: cells.get(item.column, "").strip() for item in plan.mapped}
    for field, code in target.validator(mapped).items():
        problems.append(
            RowError(
                row=row.number,
                column=plan.fields.get(field, ""),
                field=field,
                code=code,
                value=mapped.get(field, "")[:120],
            )
        )
    return problems


def _check(
    spec: FieldSpec, value: str, options: frozenset[str] | None = None
) -> str | None:
    """The one thing wrong with this cell, or nothing.

    `options` is the field's options lower-cased, when the caller has them
    already; without it they are lower-cased here, as they always were.
    """
    if not value:
        return "import.error.required" if spec.required else None
    if spec.max_length is not None and len(value) > spec.max_length:
        return "import.error.too_long"
    if spec.options:
        lowered = options or {option.lower() for option in spec.options}
        return None if value.lower() in lowered else "import.error.not_an_option"
    if spec.kind is FieldKind.INTEGER:
        # `int("1.0")` raises and `int(" 1 ")` does not, which is the behaviour
        # wanted: a decimal in an integer column is a mistake worth reporting.
        try:
            int(value)
        except ValueError:
            return "import.error.integer"
    elif spec.kind is FieldKind.DECIMAL:
        return _check_decimal(value)
    elif spec.kind is FieldKind.BOOLEAN:
        if value.lower() not in _BOOLEANS:
            return "import.error.boolean"
    elif spec.kind is FieldKind.DATE:
        if _parse_date(value) is None:
            return "import.error.date"
    elif spec.kind is FieldKind.EMAIL:
        if not _EMAIL.match(value):
            return "import.error.email"
    return None


def _check_decimal(value: str) -> str | None:
    """A number, or which of two ways it is not one.

    This did `float(value.replace(",", "."))`, which turned `1,234` -- a US
    export meaning one thousand two hundred and thirty-four -- into `1.234`.
    Not refused, not flagged, wrong by a factor of a thousand. IMP-04 in
    `docs/features/data-import/review.md`.

    The rule is the one this module already applies to dates twenty lines
    above, and for the same reason: a value that is silently wrong half the
    time is worse than one that is refused.

    - **Both separators present.** The last one is the decimal point and the
      other is thousands. Unambiguous in every locale, so it parses.
    - **One separator, followed by exactly three digits, and nothing else.**
      `1,234` and `1.234` each have two readings that differ by a thousand.
      Refused, with a code of its own so the sentence can say what to do.
    - **Anything else.** One separator followed by any other number of digits
      is a decimal point in both conventions, so it parses.
    """
    dot = value.rfind(".")
    comma = value.rfind(",")

    if dot >= 0 and comma >= 0:
        thousands = "," if dot > comma else "."
        cleaned = value.replace(thousands, "")
        cleaned = cleaned.replace(",", ".")
    elif dot >= 0 or comma >= 0:
        at = max(dot, comma)
        tail = value[at + 1 :]
        if len(tail) == 3 and tail.isdigit():
            return "import.error.ambiguous_decimal"
        cleaned = value.replace(",", ".")
    else:
        cleaned = value

    try:
        parsed = float(cleaned)
    except ValueError:
        return "import.error.decimal"
    if not math.isfinite(parsed):
        # `float()` accepts `nan`, `inf` and `1e400`, and a NaN that reaches a
        # numeric column makes every later SUM over that tenant NaN. IMP2-18.
        return "import.error.decimal"
    return None


def _canonical_decimal(value: str) -> str:
    """The number as the writer should receive it: a point, no thousands."""
    dot = value.rfind(".")
    comma = value.rfind(",")
    if dot >= 0 and comma >= 0:
        thousands = "," if dot > comma else "."
        return value.replace(thousands, "").replace(",", ".")
    return value.replace(",", ".")


def canonical(spec: FieldSpec, value: str) -> str:
    """A cell that passed `_check`, in the one shape the writer is handed.

    The validator decided `31.12.2025` was a date and then handed the writer
    `31.12.2025`, so the decision did not survive to the thing that stores it
    -- IMP2-19. Every kind with more than one accepted spelling is written
    here in exactly one: a date as ISO, a decimal with a point and no
    thousands separator, a boolean as `true` or `false`, an option as the
    target declared it. Text is text.
    """
    if not value:
        return value
    if spec.options:
        lowered = value.lower()
        for option in spec.options:
            if option.lower() == lowered:
                return option
        return value
    if spec.kind is FieldKind.DATE:
        parsed = _parse_date(value)
        return parsed.isoformat() if parsed is not None else value
    if spec.kind is FieldKind.DECIMAL:
        return _canonical_decimal(value)
    if spec.kind is FieldKind.BOOLEAN:
        lowered = value.lower()
        if lowered in _TRUE:
            return "true"
        if lowered in _FALSE:
            return "false"
    return value


def normalise_row(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> dict[str, str]:
    """The mapped, canonical row: what a writer and a matcher are given."""
    return _normalised(_plan(target, resolved), row)


def _normalised(plan: _Plan, row: Row) -> dict[str, str]:
    cells = row.cells
    return {
        item.field: canonical(item.spec, cells.get(item.column, "").strip())
        for item in plan.mapped
    }


def normaliser(
    target: ImportTarget, resolved: ResolvedMapping
) -> Callable[[Row], dict[str, str]]:
    """`normalise_row` for one target and one mapping, looked up once.

    What a commit calls for every row of a file: the same dictionary
    `normalise_row` answers, without resolving the mapping again for each.
    """
    plan = _plan(target, resolved)

    def normalise(row: Row) -> dict[str, str]:
        return _normalised(plan, row)

    return normalise


def match_key(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> tuple[str, ...] | None:
    """What makes this row the same record as another, or None if nothing does.

    One function for the in-file duplicate check and the matcher's request,
    so the product's identity semantics are applied once: stripped, canonical
    for the field's kind, and case-folded. A key with no value at all names
    nothing and is None; a partly empty key is still a key, because an empty
    part is a value the product may well store.
    """
    if not target.match_keys:
        return None
    return _key(_plan(target, resolved), row, None)


#: A key part longer than this is held once however many rows carry it.
#:
#: `str.lower` answers a new string every time, so a key part that is one long
#: shared string named by every row -- half of a two-part key, say -- became a
#: copy a row: fifty thousand rows of a 32,000-character part is 1.6 GiB of
#: one string. IMPORT-DEF-016, in the duplicate index rather than the reader.
#: Short parts are left alone: interning costs a dictionary entry, and a short
#: part repeated cannot amount to much.
_INTERN_OVER = 64


def _key(
    plan: _Plan, row: Row, interned: dict[str, str] | None
) -> tuple[str, ...] | None:
    """`match_key`, with the lookups done and long parts held once."""
    if not plan.keys:
        return None
    cells = row.cells
    parts: list[str] = []
    for spec, column in plan.keys:
        part = canonical(spec, cells.get(column, "").strip()).lower()
        if interned is not None and len(part) > _INTERN_OVER:
            # The copy `lower` just made is dropped for the one already held.
            part = interned.setdefault(part, part)
        parts.append(part)
    return tuple(parts) if any(parts) else None


def _parse_date(value: str) -> date | None:
    from datetime import datetime

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


#: What `validate` tells a caller about each row as it passes: the row, its
#: match key or None, and whether the row had any problem.
EachRow = Callable[[Row, "tuple[str, ...] | None", bool], None]


def validate(
    target: ImportTarget,
    resolved: ResolvedMapping,
    rows: Iterable[Row],
    *,
    each: EachRow | None = None,
) -> Validation:
    """Every row, one pass, every problem.

    Also catches the duplicate a file carries within itself: two rows with the
    same match key are two rows the commit would fight over, and finding that
    at commit time means finding it after half the file is written.

    **`rows` is read once and never kept**, so it may be a stream: this holds
    the problems, the keys it has seen and the numbers of the rows that had a
    problem, and nothing else of the file. `each` is how a caller takes what
    it needs of a row while the row is still there -- the matcher's keys in a
    dry run, the writer's dictionary in a commit -- without a second pass over
    rows that are no longer held. GR-352C.
    """
    plan = _plan(target, resolved)
    interned: dict[str, str] = {}
    errors: list[RowError] = []
    seen: dict[tuple[str, ...], int] = {}
    total = 0
    bad_rows: set[int] = set()
    truncated = False
    duplicates = 0

    for row in rows:
        total += 1
        problems = _problems(target, plan, row)
        key = _key(plan, row, interned)
        if key is not None:
            first = seen.get(key)
            if first is not None:
                problems.append(
                    RowError(
                        row=row.number,
                        column=plan.fields.get(target.match_keys[0], ""),
                        field=target.match_keys[0],
                        code="import.error.duplicate_in_file",
                        value=str(first),
                    )
                )
                duplicates += 1
            else:
                seen[key] = row.number

        if problems:
            bad_rows.add(row.number)
            for problem in problems:
                if len(errors) >= MAX_REPORTED_ERRORS:
                    truncated = True
                    break
                errors.append(problem)
        if each is not None:
            each(row, key, bool(problems))

    return Validation(
        rows=total,
        valid=total - len(bad_rows),
        errors=tuple(errors),
        truncated=truncated,
        duplicates=duplicates,
        bad_rows=frozenset(bad_rows),
    )
