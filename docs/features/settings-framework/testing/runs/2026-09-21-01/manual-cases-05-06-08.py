"""F27 manual cases, batch 2: the member ladder, against a real PostgreSQL."""
import asyncio, os, sys
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54323/f27check")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from koras_api.core import settings_store as store
from koras_api.settings_catalogue import catalogue
from koras_settings import Scope, ScopeRefused, check_writable, resolve_all

A = "00000000-0000-0000-0000-0000000000a1"
ME, COLLEAGUE = "member-a", "colleague-a"

async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    ok = True

    # ---- TEST-SET-06: clearing a preference gives back the organisation's value ----
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await store.write_tenant_values(s, A, {"ui.theme": "dark"})   # the organisation chooses
        await s.commit()
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await store.write_member_values(s, A, ME, {"ui.theme": "light"})  # the person disagrees
        await s.commit()

    async def effective(user: str) -> tuple[str, str]:
        async with Session() as s:
            await s.execute(text("select set_config('app.provisioning','on',true)"))
            r = resolve_all(
                catalogue,
                global_values=await store.global_values(s),
                organization_values=await store.tenant_values(s, A),
                member_values=await store.member_values(s, A, user),
            )
            answer = r.settings["ui.theme"]
            return str(answer.value), str(answer.source)

    mine, source = await effective(ME)
    if (mine, source) != ("light", "user"):
        ok = False; print(f"TEST-SET-06 FAIL (before reset): {mine}/{source}")

    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        change = await store.clear_member_value(s, A, ME, "ui.theme")
        await s.commit()
    after, after_source = await effective(ME)
    if (after, after_source) == ("dark", "organization") and change is not None:
        print("TEST-SET-06 PASS: reset returned the organisation's value (dark), not the platform's or the default")
    else:
        ok = False; print(f"TEST-SET-06 FAIL: {after}/{after_source}")

    # ---- TEST-SET-08 (member half): a colleague's preference is not mine ----
    async with Session() as s:
        await s.execute(text("select set_config('app.provisioning','on',true)"))
        await store.write_member_values(s, A, COLLEAGUE, {"ui.theme": "light"})
        await s.commit()
    mine2, _ = await effective(ME)
    theirs, theirs_source = await effective(COLLEAGUE)
    if mine2 == "dark" and (theirs, theirs_source) == ("light", "user"):
        print("TEST-SET-08 PASS (member half): a colleague's override changed nothing for me")
    else:
        ok = False; print(f"TEST-SET-08 FAIL: mine={mine2} theirs={theirs}/{theirs_source}")

    # ---- TEST-SET-05: a person cannot override what is not theirs to override ----
    org_only = [d for d in catalogue if not d.scope.admits_user and not d.system]
    if not org_only:
        ok = False; print("TEST-SET-05 FAIL: the catalogue declares no organisation-only setting")
    else:
        d = org_only[0]
        if d.user_visible:
            ok = False; print(f"TEST-SET-05 FAIL: {d.key} is offered on the preferences page")
        try:
            check_writable(d, Scope.GLOBAL_ORG_USER)
            ok = False; print(f"TEST-SET-05 FAIL: {d.key} accepted a personal override")
        except ScopeRefused as refusal:
            print(f"TEST-SET-05 PASS: {d.key} is absent from preferences and refused: {refusal.message[:60]}...")

    await engine.dispose()
    sys.exit(0 if ok else 1)

asyncio.run(main())
