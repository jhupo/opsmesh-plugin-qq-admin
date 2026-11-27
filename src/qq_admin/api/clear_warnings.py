"""Standalone public API: clear_warnings."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def clear_warnings(
    ctx: AdminContext,
    *,
    member_openid: str,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Clear active sliding-window violation records for a group member."""
    return await resolve_services(services).moderation.clear_warnings(
        ctx, member_openid=member_openid
    )


__all__ = ["clear_warnings"]
