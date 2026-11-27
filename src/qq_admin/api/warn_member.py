"""Standalone public API: warn_member."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices
from qq_admin.typing import ViolationType

from ._runtime import resolve_services


async def warn_member(
    ctx: AdminContext,
    *,
    member_openid: str,
    violation_type: ViolationType = ViolationType.OTHER,
    reason: str = "",
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Record a sliding-window violation and auto-escalate if threshold reached."""
    return await resolve_services(services).moderation.warn_member(
        ctx,
        member_openid=member_openid,
        violation_type=violation_type,
        reason=reason,
    )


__all__ = ["warn_member"]
