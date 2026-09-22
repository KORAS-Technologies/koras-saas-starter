
from koras_import import (
    FieldKind,
    FieldSpec,
    ImportTarget,
    Operation,
    WriteRequest,
    Written,
    check_total,
)

_INSERT = """
insert into public.probe_contacts (tenant_id, email, name, seats, import_run_id)
values (cast(:tenant_id as uuid), :email, :name, :seats, cast(:run_id as uuid))
on conflict (tenant_id, email) do nothing
returning id
"""

_UPSERT = """
insert into public.probe_contacts (tenant_id, email, name, seats, import_run_id)
values (cast(:tenant_id as uuid), :email, :name, :seats, cast(:run_id as uuid))
on conflict (tenant_id, email) do update
    set name = excluded.name, seats = excluded.seats,
        import_run_id = excluded.import_run_id
returning (xmax = 0) as inserted
"""


async def _write_contacts(session, request: WriteRequest) -> Written:
    """The harness writer. Never commits -- the caller owns the transaction."""
    from sqlalchemy import text

    created = 0
    updated = 0
    skipped = 0
    for row in request.rows:
        seats = row.get("seats") or None
        params = {
            "tenant_id": request.tenant_id,
            "run_id": request.run_id,
            "email": row["email"],
            "name": row["name"],
            "seats": int(seats) if seats else None,
        }
        if request.operation is Operation.UPSERT:
            result = await session.execute(text(_UPSERT), params)
            inserted = result.scalar_one()
            if inserted:
                created += 1
            else:
                updated += 1
        else:
            result = await session.execute(text(_INSERT), params)
            if result.first() is None:
                skipped += 1
            else:
                created += 1

    written = Written(created=created, updated=updated, skipped=skipped)
    check_total(request, written)
    return written


CONTACTS = ImportTarget(
    key="probe.contacts",
    label_key="import.target.probe.contacts",
    permission="imports.manage",
    fields=(
        FieldSpec(
            "email",
            "import.field.probe.contacts.email",
            kind=FieldKind.EMAIL,
            required=True,
        ),
        FieldSpec("name", "import.field.probe.contacts.name", required=True, max_length=80),
        FieldSpec("seats", "import.field.probe.contacts.seats", kind=FieldKind.INTEGER),
    ),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    writer=_write_contacts,
    attributes_to_run=True,
)

TARGETS: list[ImportTarget] = [CONTACTS]
