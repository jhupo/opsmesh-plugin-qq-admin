"""Standalone public API: kick_member."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def kick_member(
    ctx: AdminContext,
    *,
    member_openid: str,
    add_to_blacklist: bool = False,
    reason: str = "",
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Remove a group member via batch_remove_group_members after safeguard checks."""
    return await resolve_services(services).moderation.kick_member(
        ctx,
        member_openid=member_openid,
        add_to_blacklist=add_to_blacklist,
        reason=reason,
    )


__all__ = ["kick_member"]
