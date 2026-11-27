"""Standalone public API: remove_blacklist."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def remove_blacklist(
    ctx: AdminContext,
    *,
    member_openids: list[str],
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Remove member OpenIDs from the group blacklist."""
    return await resolve_services(services).moderation.manage_blacklist(
        ctx, op="del", member_openids=member_openids
    )


__all__ = ["remove_blacklist"]
