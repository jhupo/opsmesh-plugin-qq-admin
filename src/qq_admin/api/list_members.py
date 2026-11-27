"""Standalone public API: list_members."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def list_members(
    ctx: AdminContext,
    *,
    cursor: str | None = None,
    limit: int | None = 50,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """List group members with cursor pagination."""
    return await resolve_services(services).moderation.list_members(
        ctx, cursor=cursor, limit=limit
    )


__all__ = ["list_members"]
