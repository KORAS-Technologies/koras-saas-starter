"""The file hook registry admits many, refuses a repeat, and isolates a failure.

One mutable record with three fields admitted exactly one consumer until
2026-09-15: whoever installed last won, silently. These assert the three
properties that replaced it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.file_hooks import (  # noqa: E402
    FileHook,
    FileHookRegistry,
    run_after_upload,
)


def _everything(content_type: str) -> bool:
    del content_type
    return True


def _nothing(content_type: str) -> bool:
    del content_type
    return False


async def _ok(**arguments: object) -> int:
    del arguments
    return 1


def test_two_hooks_both_register_and_both_are_offered_the_upload() -> None:
    registry = FileHookRegistry()
    registry.add(FileHook(name="knowledge", interested=_everything, after_upload=_ok))
    registry.add(FileHook(name="scanner", interested=_everything, after_upload=_ok))
    assert len(registry) == 2
    assert [hook.name for hook in registry.for_upload("text/plain")] == ["knowledge", "scanner"]


def test_iteration_is_ordered_by_name_so_two_runs_agree() -> None:
    registry = FileHookRegistry()
    for name in ("scanner", "audit", "knowledge"):
        registry.add(FileHook(name=name, interested=_everything, after_upload=_ok))
    assert [hook.name for hook in registry] == ["audit", "knowledge", "scanner"]


def test_a_repeated_name_is_refused_rather_than_replacing_the_first() -> None:
    registry = FileHookRegistry()
    registry.add(FileHook(name="knowledge", interested=_everything, after_upload=_ok))
    with pytest.raises(ValueError, match="already registered"):
        registry.add(FileHook(name="knowledge", interested=_nothing, after_upload=_ok))
    assert len(registry) == 1
    assert registry.for_upload("text/plain")[0].interested("anything") is True


def test_a_hook_that_wants_nothing_of_this_type_is_not_offered_it() -> None:
    registry = FileHookRegistry()
    registry.add(FileHook(name="knowledge", interested=_nothing, after_upload=_ok))
    assert registry.for_upload("application/zip") == ()


def test_a_hook_with_no_upload_callback_is_only_a_deleter() -> None:
    async def _undo(session: object, tenant_id: str, file_id: str) -> None:
        del session, tenant_id, file_id

    registry = FileHookRegistry()
    registry.add(FileHook(name="cache", interested=_everything, before_delete=_undo))
    assert registry.for_upload("text/plain") == ()
    assert [hook.name for hook in registry.for_delete()] == ["cache"]


async def test_a_throwing_hook_does_not_become_the_uploads_problem() -> None:
    """The response is already sent when this runs, so raising reaches nobody
    who could act on it -- and one hook failing must not stop the next."""

    async def _boom(**arguments: object) -> int:
        del arguments
        raise RuntimeError("the embedder is down")

    hook = FileHook(name="knowledge", interested=_everything, after_upload=_boom)
    await run_after_upload(hook, tenant_id="t", file_id="f")
