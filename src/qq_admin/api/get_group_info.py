"""Standalone public API: get_group_info."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def get_group_info(
    ctx: AdminContext,
    *,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Fetch QQ group name, member count, description, and tags."""
    return await resolve_services(services).moderation.get_group_info(ctx)


__all__ = ["get_group_info"]
