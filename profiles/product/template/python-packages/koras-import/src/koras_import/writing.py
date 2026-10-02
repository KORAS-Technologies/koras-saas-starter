"""How a validated run becomes rows, without this package knowing any table.

The rule CAT-02 states first and could break most easily: *no product table
name, no Docoris concept and no shop concept reaches the engine.* Reading a
file, matching columns and checking values are all things this package can do
for anybody. Writing is not — a row belongs to a table the product owns, with
its own columns, its own constraints and its own idea of what makes two records
the same thing.

So the product declares a `Writer` on its target and the engine calls it. What
the engine keeps is everything that must be true whoever writes:

**One transaction, and the writer never commits.** The caller opens it, calls
the writer, and commits once at the end. A writer that committed would make a
half-written run possible, which is the one defect the requirements forbid
outright — and it is the easiest mistake to make, because committing feels like
finishing.

**Every row carries its run.** `WriteRequest.run_id` is passed so a product can
store it beside each record, which is what makes "where did this come from"
answerable a year later without an audit event per row. The engine cannot
enforce that a writer stores it; `ImportTarget` declaring `attributes_to_run`
is how a product states that it does, and a target that says so and does not is
lying in a place somebody can find.

**The operation is the product's to honour.** `skip_duplicate` and `upsert`
differ only in what they do about a match, and only the product knows how to
look one up. The engine has already refused an operation the target does not
permit, and validation has already reported duplicates *within* the file; what
is left is duplicates against what is already there.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .targets import Operation


@dataclass(frozen=True)
class WriteRequest:
    """One run's worth of validated rows, and what to do with them."""

    tenant_id: str
    #: The run these rows came from. A product stores it beside each record it
    #: creates; that reference is the provenance, and it is why an import needs
    #: no audit event per row.
    run_id: str
    operation: Operation
    #: What makes two records the same thing, as the target declared. Empty
    #: means duplicates cannot be detected, which the target's own validation
    #: has already refused for every operation that needs them.
    match_keys: tuple[str, ...]
    #: Field name to value, per row, in file order. Every value is a string:
    #: the engine checked that each parses as what its field declared, and
    #: parsing it into the product's own type is the product's business,
    #: because only the product knows what column it is going into.
    rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class Written:
    """What a writer did. The three outcomes an import can have per row.

    They must sum to the number of rows handed over. A writer that reports
    fewer has silently dropped something, and `check_total` is what turns that
    into a failure rather than a quietly short import.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    #: Anything the product wants on the run's record of what happened. Kept
    #: small: this is a summary for a person, not a second copy of the data.
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


class WriteRefused(RuntimeError):
    """A writer declined the work, and the run must record why.

    Distinct from an unexpected exception on purpose: this is the product
    saying "these rows cannot go in", which is a sentence for the customer.
    Anything else is a fault, and the run says so in different words.
    """


#: What a product supplies to make its target committable.
#:
#: Takes the caller's open session and one request; returns what it did. A
#: target with no writer is readable and validatable and **cannot be
#: committed**, which is a legitimate state — it is what every target in this
#: product was before Phase 2, and what a report-only target stays.
Writer = Callable[[Any, WriteRequest], Awaitable[Written]]


def check_total(request: WriteRequest, written: Written) -> None:
    """Refuse a writer's answer that does not account for every row.

    Cheap, and it catches the failure mode a writer is most likely to have:
    a filter or an early `continue` that skips rows without counting them. The
    run would otherwise report a clean import of fewer records than the file
    held, and nobody would know which were missing.
    """
    if written.total != len(request.rows):
        raise WriteRefused(
            f"the writer accounted for {written.total} of {len(request.rows)} rows; "
            "every row is created, updated or skipped"
        )


def rows_from(
    mapped: Sequence[Mapping[str, str]], *, ceiling: int, owned: bool = False
) -> tuple[Mapping[str, str], ...]:
    """The rows to write, refused rather than truncated past the ceiling.

    The rule audit exports already follow, and the one Phase 1 applied to
    reading: half an import is worse than none, because nobody can tell which
    half.

    **Copied, unless the caller says the rows are the writer's already.** The
    copy is what keeps a writer that mutates a row from changing something the
    caller still reads. A worker that built these dictionaries for this one
    request and reads none of them again has nothing to protect, and copying
    them is a second dictionary for every row of the file, held at the same
    moment as the first -- which is what GR-352C is about. `owned` is that
    caller saying so.
    """
    if len(mapped) > ceiling:
        raise WriteRefused(
            f"this run holds {len(mapped)} rows and the target takes {ceiling}"
        )
    if owned:
        return tuple(mapped)
    return tuple(dict(row) for row in mapped)


__all__ = [
    "WriteRefused",
    "WriteRequest",
    "Writer",
    "Written",
    "check_total",
    "rows_from",
]
