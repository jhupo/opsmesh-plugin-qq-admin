"""Standalone public API: get_audit_log."""

from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.services import AdminServices
from qq_admin.typing import AuditSource

from ._runtime import resolve_services


async def get_audit_log(
    ctx: AdminContext,
    *,
    limit: int = 20,
    source: AuditSource | None = None,
    action: str | None = None,
    services: AdminServices | None = None,
) -> ModerationOutcome:
    """Query recent structured moderation audit logs for the current group."""
    return await resolve_services(services).moderation.get_audit_log(
        ctx, limit=limit, source=source, action=action
    )


__all__ = ["get_audit_log"]
