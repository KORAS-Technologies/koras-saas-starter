"""A fixture import target, installed by `Generator Integration` and by nothing else.

**This file never ships.** It lives in `.github/fixtures/` in the starter, which
is inside no template, so `create-koras-app` cannot copy it and no generated
product contains it. The workflow writes it over the generated project's own
`services/api/koras_api/imports/targets.py` for the duration of one run.

## Why it exists

`ImportPanel` returns its no-targets banner and stops when a product declares
no targets, and a generated product declares none — correctly, because a target
names a table the *product* owns and the starter owns no domain. The
consequence was that **no CI in this estate had ever rendered the import
page**: not the picker, not the mapping, not the result card, not the report,
not the confirm control. All of it was protected by assertions that read
template text.

That is how Phase 2 shipped a commit path that could not succeed once, and a
problem report a customer could not reach after a reload. Both were found by a
person opening the page, and both are in
`docs/features/data-import/phase-2-review.md`.

`koras-e2e-shop` closed the gap on 2026-09-22 by declaring real targets over its
own domain, and is being torn down, so the gap would otherwise return. A fixture
installed by the workflow closes it for good and costs the template nothing.

## What it deliberately is not

**No writer, so not committable.** A writer needs a table, and a table in the
template is the domain this whole arrangement exists to avoid. What that costs
is the commit path — which is covered instead by
`tests/integration/test_import_commit_rls.py`, against a real PostgreSQL with
row-level security on, and by the manual cases recorded under
`docs/features/data-import/testing/`.

What it buys is everything up to the commit: that the page renders at all, that
the picker offers what the registry holds, that the module is hidden from a
member who may not import, that a past run can be opened from the history, and
that the file the browser builds from the report holds every problem once and
nothing a spreadsheet would execute.

**No product table name appears here**, which is the rule CAT-02 states first.
The fields describe a file, not a schema.
"""

from __future__ import annotations

from koras_import import FieldKind, FieldSpec, Format, ImportTarget, Operation

FIXTURE = ImportTarget(
    key="fixture.contacts",
    label_key="import.target.fixture.contacts",
    permission="imports.manage",
    fields=(
        FieldSpec(
            "email",
            "import.field.fixture.email",
            kind=FieldKind.EMAIL,
            required=True,
            help="The address the contact is reached at.",
        ),
        FieldSpec(
            "name",
            "import.field.fixture.name",
            required=True,
            max_length=200,
            example="Ada Example",
        ),
        # An enumerated column, so the template's list validation and the
        # Instructions sheet's allowed-values column both have something to
        # render on a generated product.
        FieldSpec("kind", "import.field.fixture.kind", options=("person", "organisation")),
    ),
    match_keys=("email",),
    # Both, so the operation picker has something to be a picker of. One option
    # renders a control that cannot be wrong, which tests nothing.
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    # Both formats, so the template menu has two items and the browser suite
    # can download each and open it. ADR 0012.
    formats=(Format.CSV, Format.XLSX),
    version=2,
    # No `writer`: see the module docstring. `committable` is False, which is
    # itself worth rendering — the page must draw no confirm control at all
    # rather than a disabled one.
)

TARGETS: list[ImportTarget] = [FIXTURE]
