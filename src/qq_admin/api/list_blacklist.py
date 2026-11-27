"""Standalone public API: list_blacklist."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def list_blacklist(
    ctx: AdminContext,
    *,
    cursor: str | None = None,
    limit: int | None = 50,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Query group member blacklist via get_group_member_blacklist."""
    return await resolve_services(services).moderation.list_blacklist(
        ctx, cursor=cursor, limit=limit
    )


__all__ = ["list_blacklist"]
