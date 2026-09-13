"""The tools this product's agents may propose.

One reference tool, a read: list the tenant's files, through the session the
request already opened and under the permission the Files page checks. It
proves the shape -- a typed input, a permission, an operation class, an
executor that reads its tenant from the context and never from the model --
and it is the shape every tool a product adds should have.

A write, a destructive or an external tool is declared the same way with a
different `operation`, and the runtime holds it for a person's approval; see
`koras_ai.tools` for the classes and `docs/AI_DEVELOPER_GUIDE.md` in the
starter for a worked example.
"""

from __future__ import annotations

from typing import Any

from koras_ai import Operation, ToolContext, ToolDefinition, define_tool
from pydantic import BaseModel, Field
from sqlalchemy import text


class ListFilesInput(BaseModel):
    """What the model may ask for: how many, and nothing about whose."""

    limit: int = Field(default=20, ge=1, le=100, description="How many of the newest files to list")


async def list_files(ctx: ToolContext, args: ListFilesInput) -> dict[str, Any]:
    """The tenant's ready files, newest first.

    The tenant comes from the context, which came from the verified token, and
    the session is already scoped to it. The query names it as well, the way
    every query in the API does.
    """
    if ctx.session is None:
        return {"files": [], "note": "no database session is available"}
    rows = await ctx.session.execute(
        text(
            "select name, size_bytes, content_type, ready_at from public.files "
            "where tenant_id = :tenant_id and status = 'ready' "
            "order by ready_at desc limit :limit"
        ),
        {"tenant_id": ctx.context.tenant_id, "limit": args.limit},
    )
    return {
        "files": [
            {
                "name": row.name,
                "size_bytes": row.size_bytes,
                "content_type": row.content_type,
                "uploaded_at": row.ready_at.isoformat() if row.ready_at else None,
            }
            for row in rows.fetchall()
        ]
    }


TOOLS: tuple[ToolDefinition, ...] = (
    define_tool(
        id="files.list",
        description="List the files stored in this organization, newest first.",
        permission="files.read",
        operation=Operation.READ,
        input_model=ListFilesInput,
        execute=list_files,
    ),
)
