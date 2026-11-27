"""Structured moderation audit recorder and query filter (`command`/`api`/`auto`)."""

import time
from typing import Any

from qq_admin.config import QQAdminConfig
from qq_admin.context import AdminContext
from qq_admin.store import AuditRecord, StateStoreProtocol
from qq_admin.typing import AuditSource, AuditStatus


class AuditService:
    """Append and query structured moderation audit entries."""

    def __init__(self, config: QQAdminConfig, store: StateStoreProtocol) -> None:
        self._config = config
        self._store = store

    async def record(
        self,
        ctx: AdminContext,
        *,
        action: str,
        status: AuditStatus,
        target_openid: str = "",
        detail: str = "",
        extra: dict[str, Any] | None = None,
    ) -> AuditRecord:
        entry = AuditRecord(
            trace_id=ctx.trace_id,
            timestamp=time.time(),
            group_openid=ctx.group_openid,
            action=action,
            source=ctx.source,
            status=status,
            operator_openid=ctx.operator.openid,
            operator_role=ctx.operator.effective_role,
            target_openid=target_openid,
            detail=detail,
            extra=extra or {},
        )
        await self._store.append_audit(
            entry,
            max_records_per_group=self._config.audit.max_records_per_group,
        )
        return entry

    async def query(
        self,
        group_openid: str,
        *,
        limit: int = 20,
        source: AuditSource | None = None,
        action: str | None = None,
    ) -> list[AuditRecord]:
        return await self._store.query_audits(
            group_openid, limit=limit, source=source, action=action
        )


__all__ = ["AuditService"]
