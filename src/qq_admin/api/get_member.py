"""Standalone public API: get_member."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def get_member(
    ctx: AdminContext,
    *,
    member_openid: str,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Inspect a single group member's role and join metadata."""
    return await resolve_services(services).moderation.get_member(
        ctx, member_openid=member_openid
    )


__all__ = ["get_member"]
