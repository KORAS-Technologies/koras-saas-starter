"""Loading what a customer already has into a product that has just started.

Before this package a generated product had no import of any kind: no parser,
no mapping model, no staging table, no dry run, no route and no page. The
requirements were written first, by the product that needs them —
`docoris/docs/architecture/IMPORT.md` — and the split it argued for is the one
built here: a reusable engine, and targets the product declares.

Four parts, and the first is the whole design:

``targets``
    A product declares what may be imported: the fields, which are required,
    what makes two rows the same thing, and the permission an execute needs.
    **The engine never names a product's table.** A field the import may never
    write is simply not declared, so the allowlist cannot be got wrong by
    forgetting a flag.

``states``
    The ten states a run moves through, and the only edges that exist. A run
    cannot reach ``committed`` without having been ``validated``, and
    ``committing`` has no edge to ``cancelled``.

``reading``
    A file somebody exported from something else, turned into rows: encodings
    a spreadsheet actually writes, delimiters it actually uses, headers with
    duplicate and blank names, and rows with the wrong number of cells. It
    streams.

``mapping``
    Which column is which, checked against both the target and the file — and
    whether the values under them are acceptable, every problem in one pass.

Adding a target is a declaration and two translations::

    CUSTOMERS = ImportTarget(
        key="shop.customers",
        label_key="import.target.shop.customers",
        permission="imports.manage",
        fields=(
            FieldSpec("email", "import.field.shop.customers.email",
                      kind=FieldKind.EMAIL, required=True),
            FieldSpec("name", "import.field.shop.customers.name", required=True),
        ),
        match_keys=("email",),
        operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    )

**What this package does not do**, deliberately: it opens nothing, writes
nothing and knows no SQL. A commit runs on the caller's session, under the
caller's tenant, and the engine never sees it. That is what lets the whole of
it be tested without a database, and what would let it be promoted to another
repository without a rewrite.
"""

from .jobs import COMMIT_RUN, VALIDATE_RUN
from .mapping import (
    MAX_REPORTED_ERRORS,
    MappingRefused,
    ResolvedMapping,
    RowError,
    Validation,
    resolve,
    suggest,
    validate,
    validate_row,
)
from .reading import (
    DELIMITERS,
    ENCODINGS,
    FALLBACK_ENCODING,
    MAX_CELL,
    PREVIEW_ROWS,
    Decoded,
    Header,
    ReadRefused,
    Row,
    count_rows,
    decode,
    read_header,
    read_rows,
    sniff_delimiter,
)
from .states import (
    TERMINAL,
    WROTE_NOTHING,
    RunState,
    TransitionRefused,
    is_terminal,
    may_move,
    next_states,
    require_move,
    wrote_nothing,
)
from .targets import (
    FieldKind,
    FieldSpec,
    Format,
    ImportTarget,
    Operation,
    RowValidator,
    TargetRegistry,
    build_registry,
)
from .writing import (
    Writer,
    WriteRefused,
    WriteRequest,
    Written,
    check_total,
    rows_from,
)

__all__ = [
    "COMMIT_RUN",
    "DELIMITERS",
    "ENCODINGS",
    "FALLBACK_ENCODING",
    "MAX_CELL",
    "MAX_REPORTED_ERRORS",
    "PREVIEW_ROWS",
    "TERMINAL",
    "WROTE_NOTHING",
    "Decoded",
    "FieldKind",
    "FieldSpec",
    "Format",
    "Header",
    "ImportTarget",
    "MappingRefused",
    "Operation",
    "ReadRefused",
    "ResolvedMapping",
    "Row",
    "RowError",
    "RowValidator",
    "RunState",
    "TargetRegistry",
    "TransitionRefused",
    "VALIDATE_RUN",
    "Validation",
    "WriteRefused",
    "WriteRequest",
    "Writer",
    "Written",
    "build_registry",
    "check_total",
    "count_rows",
    "decode",
    "is_terminal",
    "may_move",
    "next_states",
    "read_header",
    "read_rows",
    "require_move",
    "resolve",
    "rows_from",
    "sniff_delimiter",
    "suggest",
    "validate",
    "validate_row",
    "wrote_nothing",
]
