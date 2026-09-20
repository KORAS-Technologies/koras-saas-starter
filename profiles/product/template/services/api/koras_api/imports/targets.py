"""This product's import targets — what a customer may load, and into what.

**The extension point.** The starter ships the engine and no targets, exactly
as it ships the reporting framework with six standard reports and an empty
`reports.py`, and the settings framework with an empty `product.py`. A
generated project fills this in; nothing else changes.

There are no standard targets and there never will be. A report over
`audit_events` is the same report in every product because the table is the
platform's; an import target names a table the *product* owns, so a starter
target would be the starter guessing at a domain it does not have.

A target declares six things. Five are obvious and the sixth is the one that
matters::

    from koras_import import FieldKind, FieldSpec, ImportTarget, Operation

    CUSTOMERS = ImportTarget(
        key="shop.customers",
        label_key="import.target.shop.customers",
        # What an execute needs. The route checks it; declaring it here is what
        # lets one target be administrator-only and another wider.
        permission="imports.manage",
        fields=(
            FieldSpec(
                "email",
                "import.field.shop.customers.email",
                kind=FieldKind.EMAIL,
                required=True,
            ),
            FieldSpec("name", "import.field.shop.customers.name", required=True),
            FieldSpec("seats", "import.field.shop.customers.seats",
                      kind=FieldKind.INTEGER),
        ),
        # What makes two rows the same customer. Without it the engine refuses
        # every operation that has to recognise a row it has seen before.
        match_keys=("email",),
        operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
        validator=_no_free_mail,
    )

    TARGETS = [CUSTOMERS]

**The sixth thing is what you leave out.** A target lists the fields an import
may write and nothing else, so the allowlist cannot be got wrong by forgetting
a flag: there is no `writable=False`. An identifier, a tenant reference, a role,
a price a customer must not set — none of them is declared, and a mapping
naming one is refused rather than ignored. Ignoring it is how an import writes
a column it was never meant to reach.

Two more things worth knowing before the first target.

**The engine's checks run first, then yours.** A validator is handed a row that
has already passed the field kinds, so it never re-checks that a number is a
number, and it never runs against a row it would only report twice.

**Every label is a key.** `label_key` and each field's own resolve through
`packages/i18n`, so a target is a declaration and three translations. A
sentence here is an English sentence in a German customer's mapping screen.
"""

from __future__ import annotations

from koras_import import ImportTarget

#: Read by `koras_api.imports` and registered at import. Empty in a freshly
#: generated project, because the starter has no domain of its own.
TARGETS: list[ImportTarget] = []
