"""What may be imported, declared by the product that owns the table.

**The engine never names a product's tables.** A product declares a target —
its fields, which of them are required, what makes two rows the same thing, and
which permission an execute needs — and the engine reads files, maps columns
and validates against that declaration. This is the same seam the report
catalogue and the settings catalogue already use, for the same reason: an
engine that knew `shop.customers` would have to be forked to import anything
else.

**A field the import may never write is simply not declared.** There is no
`writable=False`; a target lists what may be written and nothing else, so the
allowlist cannot be got wrong by forgetting a flag. An identifier, a tenant
reference or a role is absent from `fields`, and a mapping naming one is
refused rather than ignored — ignoring it is how an import writes a column it
was never meant to reach.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

#: The shape an audit action, a report key and a task name already use.
_DOTTED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: A target field's own name, as it appears in a mapping and in an error.
_FIELD = re.compile(r"^[a-z][a-z0-9_]*$")


class Operation(StrEnum):
    """What a run may do to a row that already exists, or does not.

    **Delete, merge and replace are absent, and their absence is the
    decision.** An import is a way to get data in; a way to remove data in bulk
    is a different feature with a different confirmation, and one that arrived
    as an operation on this enum would arrive without either. A product that
    needs to retire rows in bulk asks for that feature rather than passing a
    flag to this one.
    """

    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"
    #: Create what is new and leave alone what is not. The default, because it
    #: is the only operation that cannot overwrite something a person meant to
    #: keep.
    SKIP_DUPLICATE = "skip_duplicate"


class Format(StrEnum):
    CSV = "csv"
    #: Phase 3. Declared now so a target can say which formats it accepts
    #: before the reader exists, and the engine refuses the ones it cannot read
    #: rather than a target having to be edited later.
    XLSX = "xlsx"
    JSON = "json"


class FieldKind(StrEnum):
    """What a cell has to look like before a product's own rules see it.

    Deliberately small. These are the checks that are the same for every
    product — a number is a number, a date is a date — and everything else is
    the target's own validator, which knows what a valid account code is and
    this does not.
    """

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    EMAIL = "email"


@dataclass(frozen=True)
class FieldSpec:
    """One column a target accepts."""

    name: str
    #: `import.field.<target>.<name>`, resolved by the browser. Never prose: a
    #: label here would be an English label shipped to a German customer.
    label_key: str
    kind: FieldKind = FieldKind.TEXT
    required: bool = False
    max_length: int | None = None
    #: For an enumerated column — a status, a type. Compared case-insensitively
    #: and stored as declared, because a spreadsheet's capitalisation is
    #: whatever the person typing felt like.
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _FIELD.match(self.name):
            raise ValueError(
                f"field name {self.name!r} must be lower-case with underscores"
            )
        if not self.label_key.strip():
            raise ValueError(f"field {self.name} needs a label key")
        if self.max_length is not None and self.max_length < 1:
            raise ValueError(f"field {self.name} has a max_length below 1")
        if self.options and self.kind is not FieldKind.TEXT:
            raise ValueError(
                f"field {self.name} has options and is not text; an enumerated "
                "column is text with a closed set"
            )


#: A product's own rule for one mapped row. Returns the problems it found, by
#: field name; an empty mapping means the row is acceptable. It is handed the
#: row *after* the engine's own field checks have passed, so it never has to
#: re-check that a number is a number.
RowValidator = Callable[[Mapping[str, str]], Mapping[str, str]]


@dataclass(frozen=True)
class ImportTarget:
    """One thing a product will accept an import into."""

    key: str
    label_key: str
    #: What an execute needs. Checked by the route, not here: a permission this
    #: declared and nothing enforced would be worse than none at all.
    permission: str
    fields: tuple[FieldSpec, ...]
    #: What makes two rows the same thing. Empty means duplicates cannot be
    #: detected, which forces `CREATE` as the only operation — stated here
    #: rather than discovered when an upsert silently creates a second row.
    match_keys: tuple[str, ...] = ()
    operations: tuple[Operation, ...] = (Operation.SKIP_DUPLICATE,)
    formats: tuple[Format, ...] = (Format.CSV,)
    #: The ceiling a single run may carry. Refused rather than truncated, which
    #: is the rule audit exports already follow: half an import is worse than
    #: none, because nobody can tell which half.
    max_rows: int = 50_000
    validator: RowValidator | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _DOTTED.match(self.key):
            raise ValueError(
                f"target key {self.key!r} must be dotted lower-case, "
                "like 'shop.customers'"
            )
        if not self.fields:
            raise ValueError(f"target {self.key} declares no fields to import")
        names = [spec.name for spec in self.fields]
        duplicated = {name for name in names if names.count(name) > 1}
        if duplicated:
            raise ValueError(
                f"target {self.key} declares {sorted(duplicated)} more than once"
            )
        if not self.operations:
            raise ValueError(f"target {self.key} permits no operation")
        unknown = set(self.match_keys) - set(names)
        if unknown:
            raise ValueError(
                f"target {self.key} matches on {sorted(unknown)}, which it does "
                "not declare as a field"
            )
        needs_match = {Operation.UPDATE, Operation.UPSERT, Operation.SKIP_DUPLICATE}
        if not self.match_keys and needs_match.intersection(self.operations):
            raise ValueError(
                f"target {self.key} permits an operation that has to recognise "
                "a row it has seen before, and declares no match keys"
            )
        if not self.permission.strip():
            raise ValueError(f"target {self.key} names no permission")
        if self.max_rows < 1:
            raise ValueError(f"target {self.key} has a max_rows below 1")

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields)

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields if spec.required)

    def spec(self, name: str) -> FieldSpec:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        raise KeyError(f"target {self.key} declares no field {name!r}")

    def accepts(self, fmt: Format) -> bool:
        return fmt in self.formats


class TargetRegistry:
    """Every target this product accepts.

    The registry shape used by reports, audit actions, settings, file hooks and
    notification kinds: built at import, a duplicate key raises with a
    traceback rather than resolving silently, iteration is sorted, and an
    unknown key raises rather than defaulting.
    """

    def __init__(self) -> None:
        self._targets: dict[str, ImportTarget] = {}

    def add(self, target: ImportTarget) -> None:
        if target.key in self._targets:
            raise ValueError(
                f"import target {target.key} is registered twice; one "
                "declaration would silently win over the other"
            )
        self._targets[target.key] = target

    def extend(self, targets: Iterable[ImportTarget]) -> None:
        for target in targets:
            self.add(target)

    def require(self, key: str) -> ImportTarget:
        """The target, or a refusal naming it.

        Raising beats defaulting: a key nobody declared is a caller asking to
        write somewhere the product never offered, and the only safe answer to
        that is no.
        """
        try:
            return self._targets[key]
        except KeyError:
            raise KeyError(
                f"import target {key!r} was never registered; a product "
                "declares what may be imported in its own targets module"
            ) from None

    def __contains__(self, key: object) -> bool:
        return key in self._targets

    def __iter__(self) -> Iterator[ImportTarget]:
        return iter(sorted(self._targets.values(), key=lambda target: target.key))

    def __len__(self) -> int:
        return len(self._targets)

    def clear(self) -> None:
        """Tests only."""
        self._targets.clear()


def build_registry(*groups: Sequence[ImportTarget]) -> TargetRegistry:
    """One registry from several declaration lists.

    Variadic so a traceback names which group collided — the same reason the
    settings catalogue takes its groups this way.
    """
    registry = TargetRegistry()
    for group in groups:
        registry.extend(group)
    return registry
