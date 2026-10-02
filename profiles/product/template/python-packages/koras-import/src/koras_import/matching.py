"""What an import would do, predicted before it does it.

The dry run could always say which rows were wrong. It could not say what the
right ones would *do* -- create a record, update one, leave one alone -- because
only the product can look a record up, and the dry run never called the
product. The matcher is that one call: a product declares it on the target
beside the writer, the engine asks it once per run which of the file's match
keys already name a record, and the prediction follows from the operation.

**The matcher reads and nothing else.** It takes the caller's session, which
is bound to the tenant, and answers a set. It is called once with every key
rather than once per row, because a file of fifty thousand rows is fifty
thousand queries the other way.

**A prediction is a prediction.** The commit runs the writer, and the writer
decides again with the rows in front of it and a transaction around it. A
record created between the dry run and the confirm makes the prediction wrong
and the commit right, which is the correct order for those two to be wrong in.

**Reject is a row error.** With `create`, a row that names an existing record
cannot be added and is reported like any other problem, which puts the run in
`validation_failed` with the row named -- rather than a commit that refuses
the whole file for a reason the report never listed. ADR 0012 D3 and D9.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Iterable
from dataclasses import dataclass, replace
from typing import Any

from .mapping import MAX_REPORTED_ERRORS, ResolvedMapping, RowError, Validation, match_key
from .reading import Row
from .targets import ImportTarget, Operation

ALREADY_EXISTS = "import.error.already_exists"


@dataclass(frozen=True)
class MatchRequest:
    """What a matcher is asked: which of these keys name a record you hold."""

    tenant_id: str
    target: str
    #: The field names, in the order every key's parts are given.
    match_keys: tuple[str, ...]
    #: Every distinct key in the file's valid rows, canonical and case-folded,
    #: in file order.
    keys: tuple[tuple[str, ...], ...]


Matcher = Callable[[Any, MatchRequest], Awaitable[Collection[tuple[str, ...]]]]


@dataclass(frozen=True)
class Prediction:
    create: int = 0
    update: int = 0
    skip: int = 0
    reject: int = 0
    #: One per rejected row, to be merged into the verdict.
    errors: tuple[RowError, ...] = ()


def keys_of(
    target: ImportTarget, resolved: ResolvedMapping, rows: Iterable[Row], *, bad: Collection[int]
) -> tuple[tuple[str, ...], ...]:
    """Every distinct key among the rows the validator passed, in file order."""
    found: dict[tuple[str, ...], None] = {}
    for row in rows:
        if row.number in bad:
            continue
        key = match_key(target, resolved, row)
        if key is not None:
            found.setdefault(key, None)
    return tuple(found)


def request_for(
    target: ImportTarget,
    resolved: ResolvedMapping,
    rows: Iterable[Row],
    *,
    tenant_id: str,
    verdict: Validation,
) -> MatchRequest:
    return MatchRequest(
        tenant_id=tenant_id,
        target=target.key,
        match_keys=tuple(target.match_keys),
        keys=keys_of(target, resolved, rows, bad=verdict.bad_rows),
    )


def predict(
    target: ImportTarget,
    operation: Operation,
    resolved: ResolvedMapping,
    rows: Iterable[Row],
    *,
    verdict: Validation,
    existing: Collection[tuple[str, ...]],
) -> Prediction:
    """Counts by what the operation does to a row that exists, or does not.

    | operation      | exists  | does not exist |
    |----------------|---------|----------------|
    | create         | reject  | create         |
    | update         | update  | skip           |
    | upsert         | update  | create         |
    | skip_duplicate | skip    | create         |

    A row with no key at all -- every match field empty -- cannot name an
    existing record and is counted as whatever a new row is under the
    operation. A key the file repeats was already reported as a duplicate and
    its later rows are in `bad_rows`, so each key is counted once.
    """
    known = set(existing)
    create = update = skip = reject = 0
    errors: list[RowError] = []
    for row in rows:
        if row.number in verdict.bad_rows:
            continue
        key = match_key(target, resolved, row)
        found = key is not None and key in known
        if operation is Operation.CREATE:
            if found:
                reject += 1
                errors.append(
                    RowError(
                        row=row.number,
                        column=resolved.fields.get(target.match_keys[0], ""),
                        field=target.match_keys[0] if target.match_keys else "",
                        code=ALREADY_EXISTS,
                        value=(row.cells.get(resolved.fields.get(target.match_keys[0], ""), "")
                               if target.match_keys else "")[:120],
                    )
                )
            else:
                create += 1
        elif operation is Operation.UPDATE:
            if found:
                update += 1
            else:
                skip += 1
        elif operation is Operation.UPSERT:
            if found:
                update += 1
            else:
                create += 1
        else:
            if found:
                skip += 1
            else:
                create += 1
    return Prediction(
        create=create, update=update, skip=skip, reject=reject, errors=tuple(errors)
    )


@dataclass(frozen=True)
class Candidates:
    """What a dry run keeps of the rows it passed, so a matcher can be asked.

    `request_for` and `predict` are handed every row of the file, twice. A
    worker that reads rows as a stream has none to hand over once they have
    gone by, and does not need them: of a row the validator passed, the
    prediction uses its key, its number, and -- under `create` alone -- the
    cell a rejection quotes. Those are kept here and the row is not.

    **Each key is in the file once among these rows.** A second row carrying
    a key is a duplicate, which is a problem, which is not a row the validator
    passed. So `keys` is `keys_of`'s answer already: distinct, in file order.
    """

    #: The key of each row that passed and has one, in file order.
    keys: tuple[tuple[str, ...], ...] = ()
    #: That row's number, beside its key.
    rows: tuple[int, ...] = ()
    #: That row's first match-key cell, cut as a problem's value is cut.
    values: tuple[str, ...] = ()
    #: Rows that passed and carry no key at all. They cannot name a record.
    unkeyed: int = 0


class Candidate:
    """Collects `Candidates` from `validate`, a row at a time.

    Pass `collect` as `validate`'s `each`. The key it is given for a row that
    passed is the very tuple the validator's duplicate index holds, so keeping
    it here keeps no second copy of any key.
    """

    def __init__(self, target: ImportTarget, resolved: ResolvedMapping) -> None:
        self._column = (
            resolved.fields.get(target.match_keys[0], "") if target.match_keys else ""
        )
        self._keys: list[tuple[str, ...]] = []
        self._rows: list[int] = []
        self._values: list[str] = []
        self._unkeyed = 0

    def collect(self, row: Row, key: tuple[str, ...] | None, bad: bool) -> None:
        if bad:
            return
        if key is None:
            self._unkeyed += 1
            return
        self._keys.append(key)
        self._rows.append(row.number)
        self._values.append(row.cells.get(self._column, "")[:120])

    def candidates(self) -> Candidates:
        return Candidates(
            keys=tuple(self._keys),
            rows=tuple(self._rows),
            values=tuple(self._values),
            unkeyed=self._unkeyed,
        )


def request_from(
    target: ImportTarget, candidates: Candidates, *, tenant_id: str
) -> MatchRequest:
    """`request_for`, from what a streamed dry run kept."""
    return MatchRequest(
        tenant_id=tenant_id,
        target=target.key,
        match_keys=tuple(target.match_keys),
        keys=candidates.keys,
    )


def predict_from(
    target: ImportTarget,
    operation: Operation,
    resolved: ResolvedMapping,
    candidates: Candidates,
    *,
    existing: Collection[tuple[str, ...]],
) -> Prediction:
    """`predict`, from what a streamed dry run kept. The same table, row for row.

    Held to `predict` by `test_matching.py`, which hands both the same files
    under every operation and compares the answers whole.
    """
    known = set(existing)
    found = 0
    errors: list[RowError] = []
    reject = operation is Operation.CREATE
    field = target.match_keys[0] if target.match_keys else ""
    column = resolved.fields.get(field, "")
    for key, number, value in zip(
        candidates.keys, candidates.rows, candidates.values, strict=True
    ):
        if key not in known:
            continue
        found += 1
        if reject:
            errors.append(
                RowError(
                    row=number,
                    column=column,
                    field=field,
                    code=ALREADY_EXISTS,
                    value=value,
                )
            )
    absent = len(candidates.keys) - found + candidates.unkeyed
    if operation is Operation.CREATE:
        return Prediction(create=absent, reject=found, errors=tuple(errors))
    if operation is Operation.UPDATE:
        return Prediction(update=found, skip=absent)
    if operation is Operation.UPSERT:
        return Prediction(update=found, create=absent)
    return Prediction(skip=found, create=absent)


def with_rejections(verdict: Validation, prediction: Prediction) -> Validation:
    """The verdict with every rejected row added as a problem, bounded as before."""
    if not prediction.errors:
        return verdict
    errors = list(verdict.errors)
    truncated = verdict.truncated
    for problem in prediction.errors:
        if len(errors) >= MAX_REPORTED_ERRORS:
            truncated = True
            break
        errors.append(problem)
    rejected = {problem.row for problem in prediction.errors}
    bad = frozenset(verdict.bad_rows | rejected)
    return replace(
        verdict,
        valid=verdict.rows - len(bad),
        errors=tuple(errors),
        truncated=truncated,
        bad_rows=bad,
    )


__all__ = [
    "ALREADY_EXISTS",
    "Candidate",
    "Candidates",
    "MatchRequest",
    "Matcher",
    "Prediction",
    "keys_of",
    "predict",
    "predict_from",
    "request_for",
    "request_from",
    "with_rejections",
]
