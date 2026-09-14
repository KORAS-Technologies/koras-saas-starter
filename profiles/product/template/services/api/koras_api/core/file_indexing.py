"""The assistant's half of the files routes: index on upload, forget on delete.

Installed from `main.py` when the capability is generated. Nothing is
installed without a gateway to embed through: the Files page then says
*pending* for nothing, because nothing was ever going to be read.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from . import knowledge
from .ai import index_uploaded_file
from .file_hooks import hooks
from .settings import settings


async def _remove(session: AsyncSession, tenant_id: str, file_id: str) -> None:
    await knowledge.delete_resource(
        session, tenant_id=tenant_id, resource_type="file", resource_id=file_id
    )


def install() -> None:
    if not settings.ai_gateway_url:
        return
    hooks.indexable = knowledge.is_indexable
    hooks.index = index_uploaded_file
    hooks.remove = _remove
