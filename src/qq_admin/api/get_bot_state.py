"""Standalone public API: get_bot_state."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def get_bot_state(
    ctx: AdminContext,
    *,
    force_refresh: bool = False,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Query bot role (owner/admin/member) and proactive message state."""
    return await resolve_services(services).moderation.get_bot_state(
        ctx, force_refresh=force_refresh
    )


__all__ = ["get_bot_state"]
