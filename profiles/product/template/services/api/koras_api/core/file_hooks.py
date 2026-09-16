"""What the files routes do beside storing a file, when something asks.

The files module is generated always; the things that want to hear about an
upload are not. The router cannot import what may not exist, so it calls
through here and each interested module registers itself at startup.

This was one mutable record with three fields until 2026-09-15, which admitted
exactly one consumer: the assistant's indexer took the slot at startup, and a
malware scanner arriving second would have replaced it rather than joined it,
silently and at import order. It is a registry now, in the shape
`koras_reporting` uses -- a duplicate name is refused where it is a traceback
rather than a mystery at request time, and iteration is ordered by name so two
runs of the same build do the same thing in the same order.

Nothing registered is the normal case, and then every list here is empty.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileHook:
    """One module's interest in what happens to a file.

    `name` identifies the registration and is what a duplicate is refused on.
    Both callbacks are optional: a scanner may want uploads and nothing else,
    and a cache may want deletions and nothing else.
    """

    name: str
    #: Whether a completed upload of this content type concerns this hook.
    interested: Callable[[str], bool]
    #: Handle one finished upload, after the response. Keyword arguments:
    #: tenant_id, organization_id, token, file_id, name, content_type, url,
    #: user_id. None when this hook does not want uploads.
    after_upload: Callable[..., Awaitable[int]] | None = None
    #: Undo what this hook did for a file, on the request's session, before
    #: the row goes. None when there is nothing to undo.
    before_delete: Callable[[AsyncSession, str, str], Awaitable[None]] | None = None


class FileHookRegistry:
    """Named hooks, refused on duplicate, iterated in one order."""

    def __init__(self) -> None:
        self._hooks: dict[str, FileHook] = {}

    def add(self, hook: FileHook) -> None:
        if hook.name in self._hooks:
            raise ValueError(f"a file hook named {hook.name!r} is already registered")
        self._hooks[hook.name] = hook

    def clear(self) -> None:
        """For tests, and for a second `install()` in one process."""
        self._hooks.clear()

    def __iter__(self) -> Iterator[FileHook]:
        return iter(sorted(self._hooks.values(), key=lambda hook: hook.name))

    def __len__(self) -> int:
        return len(self._hooks)

    def for_upload(self, content_type: str) -> tuple[FileHook, ...]:
        return tuple(
            hook for hook in self if hook.after_upload is not None and hook.interested(content_type)
        )

    def for_delete(self) -> tuple[FileHook, ...]:
        return tuple(hook for hook in self if hook.before_delete is not None)


hooks = FileHookRegistry()


async def run_after_upload(hook: FileHook, /, **arguments: object) -> None:
    """Run one upload hook, and never let it become the upload's problem.

    The response has already been sent by the time this runs, so raising here
    reaches nobody who could act on it, and one hook throwing must not stop
    the next hook from running. The file's own row records the outcome where
    the hook writes one.
    """
    if hook.after_upload is None:
        return
    try:
        await hook.after_upload(**arguments)
    except Exception:
        logger.exception("the file hook %s failed after an upload", hook.name)
