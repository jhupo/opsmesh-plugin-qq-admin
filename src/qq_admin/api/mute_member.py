"""Standalone public API: mute_member."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def mute_member(
    ctx: AdminContext,
    *,
    member_openid: str,
    duration_seconds: int = 600,
    reason: str = "",
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Apply a guarded timed mute via set_group_members_mute(op='add')."""
    return await resolve_services(services).moderation.mute_member(
        ctx,
        member_openid=member_openid,
        duration_seconds=duration_seconds,
        reason=reason,
    )


__all__ = ["mute_member"]
