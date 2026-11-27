"""Standalone public API: unmute_member."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def unmute_member(
    ctx: AdminContext,
    *,
    member_openid: str,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Lift mute state for a member via set_group_members_mute(op='del')."""
    return await resolve_services(services).moderation.unmute_member(
        ctx, member_openid=member_openid
    )


__all__ = ["unmute_member"]
