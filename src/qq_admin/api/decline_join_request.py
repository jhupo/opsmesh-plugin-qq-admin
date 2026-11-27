"""Standalone public API: decline_join_request."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def decline_join_request(
    ctx: AdminContext,
    *,
    member_openid: str,
    join_request_id: str | None = None,
    reject_reason: str | None = None,
    add_to_blacklist: bool = False,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Decline a pending group join request with optional reason and blacklist."""
    return await resolve_services(services).moderation.decide_join_request(
        ctx,
        member_openid=member_openid,
        op="decline",
        join_request_id=join_request_id,
        reject_reason=reject_reason,
        add_to_blacklist=add_to_blacklist,
    )


__all__ = ["decline_join_request"]
