"""What an import would do, predicted from what the product says exists.

The matcher is the product's; these tests give it a set and assert the engine
asks once, asks only about rows the validator passed, and counts by the
operation's table. The one prediction that changes the verdict is `create`
against a record that exists: that is a row error, reported like any other,
so the run lands in `validation_failed` with the row named.
"""

from __future__ import annotations

from koras_import import (
    ALREADY_EXISTS,
    FieldKind,
    FieldSpec,
    ImportTarget,
    Operation,
    Row,
    predict,
    request_for,
    resolve,
    validate,
    with_rejections,
)

CUSTOMERS = ImportTarget(
    key="shop.customers",
    label_key="import.target.shop.customers",
    permission="imports.manage",
    fields=(
        FieldSpec("email", "import.field.email", kind=FieldKind.EMAIL, required=True),
        FieldSpec("name", "import.field.name", required=True),
    ),
    match_keys=("email",),
    operations=tuple(Operation),
)

RESOLVED = resolve(CUSTOMERS, ("Email", "Name"), {"Email": "email", "Name": "name"})


def row(number: int, email: str, name: str = "Somebody") -> Row:
    return Row(number=number, cells={"Email": email, "Name": name}, short=False, long=False)


ROWS = (
    row(2, "ada@example.com"),
    row(3, "Bo@Example.com"),
    row(4, "cy@example.com"),
    row(5, "not-an-address"),  # invalid: never asked about, never counted
    row(6, "ADA@example.com"),  # an in-file duplicate of row 2
)
VERDICT = validate(CUSTOMERS, RESOLVED, ROWS)


def test_the_request_names_each_key_once_canonical_and_only_for_valid_rows() -> None:
    request = request_for(CUSTOMERS, RESOLVED, ROWS, tenant_id="t-1", verdict=VERDICT)
    assert request.tenant_id == "t-1"
    assert request.target == "shop.customers"
    assert request.match_keys == ("email",)
    assert request.keys == (("ada@example.com",), ("bo@example.com",), ("cy@example.com",))


def test_the_in_file_duplicate_is_a_figure_of_its_own() -> None:
    assert VERDICT.duplicates == 1
    assert VERDICT.bad_rows == frozenset({5, 6})


def test_counts_follow_the_operation_table() -> None:
    existing = {("ada@example.com",)}
    by_operation = {
        operation: predict(
            CUSTOMERS, operation, RESOLVED, ROWS, verdict=VERDICT, existing=existing
        )
        for operation in Operation
    }
    assert (by_operation[Operation.CREATE].reject, by_operation[Operation.CREATE].create) == (1, 2)
    assert (by_operation[Operation.UPDATE].update, by_operation[Operation.UPDATE].skip) == (1, 2)
    assert (by_operation[Operation.UPSERT].update, by_operation[Operation.UPSERT].create) == (1, 2)
    assert (
        by_operation[Operation.SKIP_DUPLICATE].skip,
        by_operation[Operation.SKIP_DUPLICATE].create,
    ) == (1, 2)
    # Nothing is predicted for a row the validator refused.
    for prediction in by_operation.values():
        assert prediction.create + prediction.update + prediction.skip + prediction.reject == 3


def test_a_rejection_is_a_row_error_that_changes_the_verdict() -> None:
    prediction = predict(
        CUSTOMERS,
        Operation.CREATE,
        RESOLVED,
        ROWS,
        verdict=VERDICT,
        existing={("ada@example.com",)},
    )
    assert [(e.row, e.field, e.code, e.value) for e in prediction.errors] == [
        (2, "email", ALREADY_EXISTS, "ada@example.com")
    ]
    merged = with_rejections(VERDICT, prediction)
    assert merged.ok is False
    assert merged.valid == VERDICT.valid - 1
    assert 2 in merged.bad_rows
    assert merged.errors[-1].code == ALREADY_EXISTS


def test_no_rejections_leave_the_verdict_as_it_was() -> None:
    prediction = predict(
        CUSTOMERS, Operation.UPSERT, RESOLVED, ROWS, verdict=VERDICT, existing=set()
    )
    assert prediction.errors == ()
    assert with_rejections(VERDICT, prediction) is VERDICT


def test_a_row_with_no_key_at_all_is_a_new_row() -> None:
    no_key = ImportTarget(
        key="shop.notes",
        label_key="import.target.shop.notes",
        permission="imports.manage",
        fields=(
            FieldSpec("code", "import.field.code"),
            FieldSpec("text", "import.field.text", required=True),
        ),
        match_keys=("code",),
        operations=(Operation.SKIP_DUPLICATE,),
    )
    resolved = resolve(no_key, ("Code", "Text"), {"Code": "code", "Text": "text"})
    rows = (Row(number=2, cells={"Code": "", "Text": "hello"}, short=False, long=False),)
    verdict = validate(no_key, resolved, rows)
    prediction = predict(
        no_key, Operation.SKIP_DUPLICATE, resolved, rows, verdict=verdict, existing={("",)}
    )
    assert (prediction.create, prediction.skip) == (1, 0)
