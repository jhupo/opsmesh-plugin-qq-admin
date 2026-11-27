"""Standalone public API: add_blacklist."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def add_blacklist(
    ctx: AdminContext,
    *,
    member_openids: list[str],
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Add member OpenIDs to the group blacklist."""
    return await resolve_services(services).moderation.manage_blacklist(
        ctx, op="add", member_openids=member_openids
    )


__all__ = ["add_blacklist"]
