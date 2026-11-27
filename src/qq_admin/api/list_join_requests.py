"""Standalone public API: list_join_requests."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def list_join_requests(
    ctx: AdminContext,
    *,
    cursor: str | None = None,
    limit: int | None = 50,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """List pending join requests via get_group_join_request_list."""
    return await resolve_services(services).moderation.list_join_requests(
        ctx, cursor=cursor, limit=limit
    )


__all__ = ["list_join_requests"]
