"""Standalone public API: approve_join_request."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def approve_join_request(
    ctx: AdminContext,
    *,
    member_openid: str,
    join_request_id: str | None = None,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Approve a pending group join request."""
    return await resolve_services(services).moderation.decide_join_request(
        ctx,
        member_openid=member_openid,
        op="approve",
        join_request_id=join_request_id,
    )


__all__ = ["approve_join_request"]
