"""What the files routes do beside storing a file, when a capability asks.

The files module is generated always; the assistant is a capability. The
router cannot import what may not exist, so it calls through here, and the
capability installs itself at startup (`core/file_indexing.py`, from
`main.py`) when it is present and configured. Absent, every hook is the
default: nothing is indexable, nothing is indexed, nothing is removed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession


def _nothing_is_indexable(content_type: str) -> bool:
    del content_type
    return False


@dataclass
class FileHooks:
    #: Whether a completed upload of this type is worth reading back.
    indexable: Callable[[str], bool] = field(default=_nothing_is_indexable)
    #: Index one finished upload, after the response. Keyword arguments:
    #: tenant_id, organization_id, token, file_id, name, content_type, url,
    #: user_id. None when nothing indexes.
    index: Callable[..., Awaitable[int]] | None = None
    #: Remove what was indexed for a file, on the request's session, before
    #: the row goes. None when nothing was ever indexed.
    remove: Callable[[AsyncSession, str, str], Awaitable[None]] | None = None


hooks = FileHooks()
