"""F27 manual cases executed against a real PostgreSQL with the product's own code."""
import asyncio, os, sys
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54323/f27check")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from koras_api.core import settings_store as store
from koras_api.settings_catalogue import catalogue

A = "00000000-0000-0000-0000-0000000000a1"
B = "00000000-0000-0000-0000-0000000000b1"

async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    ok = True

    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await s.execute(text("delete from public.tenant_setting_values where tenant_id in (cast(:a as uuid), cast(:b as uuid))"), {"a": A, "b": B})
        await s.execute(text("delete from public.tenants where id in (cast(:a as uuid), cast(:b as uuid))"), {"a": A, "b": B})
        await s.execute(text("delete from public.global_settings"))
        await s.execute(text("insert into public.tenants (id, slug, name) values (cast(:a as uuid),'mt-a','A')"), {"a": A})
        await s.commit()

    # ---- TEST-SET-02: the snapshot does not follow the platform ----
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        v_a = await store.seed_tenant(s, A, catalogue)
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        version, _ = await store.write_global_values(s, {"grid.pageSize": 10})
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await s.execute(text("insert into public.tenants (id, slug, name) values (cast(:b as uuid),'mt-b','B')"), {"b": B})
        v_b = await store.seed_tenant(s, B, catalogue)
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        a_vals = await store.tenant_values(s, A)
        b_vals = await store.tenant_values(s, B)
    a_page, b_page = a_vals.get("grid.pageSize"), b_vals.get("grid.pageSize")
    if a_page == 50 and b_page == 10:
        print(f"TEST-SET-02 PASS: A kept {a_page} after the platform moved to 10; B was seeded {b_page}")
    else:
        ok = False; print(f"TEST-SET-02 FAIL: A={a_page} B={b_page}")

    # ---- TEST-SET-03: what was copied, and when, is recorded ----
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        rows = (await s.execute(text(
            "select id::text, settings_global_version, settings_copied_at, settings_copied_by "
            "from public.tenants where id in (cast(:a as uuid), cast(:b as uuid)) order by settings_copied_at"),
            {"a": A, "b": B})).all()
    if len(rows) == 2 and all(r[1] is not None and r[2] is not None and r[3] for r in rows) \
       and rows[0][2] != rows[1][2] and rows[1][1] > rows[0][1]:
        print(f"TEST-SET-03 PASS: versions {rows[0][1]} then {rows[1][1]}, distinct timestamps, copied_by={rows[0][3]!r}")
    else:
        ok = False; print(f"TEST-SET-03 FAIL: {rows}")

    # ---- TEST-SET-07: an organisation reset is a copy, not a delete ----
    definition = catalogue.require("grid.pageSize")
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await store.write_tenant_values(s, A, {"grid.pageSize": 250})
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await store.reset_tenant_value(s, A, definition)
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        present = (await s.execute(text(
            "select value from public.tenant_setting_values "
            "where tenant_id = cast(:a as uuid) and key = 'grid.pageSize'"), {"a": A})).first()
    if present is not None and present[0] == 10:
        print("TEST-SET-07 PASS: the row still exists and holds the platform's current value (10)")
    else:
        ok = False; print(f"TEST-SET-07 FAIL: {present}")

    await engine.dispose()
    sys.exit(0 if ok else 1)

asyncio.run(main())
