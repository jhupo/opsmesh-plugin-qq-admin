"""Standalone public API: recall_message."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices

from ._runtime import resolve_services


async def recall_message(
    ctx: AdminContext,
    *,
    message_id: str,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Recall a group message within Tencent's 2-minute window."""
    return await resolve_services(services).moderation.recall_message(
        ctx, message_id=message_id
    )


__all__ = ["recall_message"]
