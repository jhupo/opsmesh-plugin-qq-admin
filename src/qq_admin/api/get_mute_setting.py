"""Standalone public API: get_mute_setting."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def get_mute_setting(
    ctx: AdminContext,
    *,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Inspect current group mute setting and muted member list."""
    return await resolve_services(services).moderation.get_mute_setting(ctx)


__all__ = ["get_mute_setting"]
