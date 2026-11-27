"""Async state storage protocol and domain record schemas."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from qq_admin.typing import AuditSource, AuditStatus, RoleTier, ViolationType


class QuotaCheckResult(BaseModel):
    """Result of an atomic daily quota check and consumption."""

    allowed: bool
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)


class ViolationRecord(BaseModel):
    """Single recorded member violation inside a sliding window."""

    group_openid: str
    member_openid: str
    violation_type: ViolationType = ViolationType.OTHER
    reason: str = ""
    operator_openid: str = ""
    timestamp: float


class AuditRecord(BaseModel):
    """Structured audit log entry for every command, tool, or auto action."""

    trace_id: str
    timestamp: float
    group_openid: str
    action: str
    source: AuditSource
    status: AuditStatus
    operator_openid: str
    operator_role: RoleTier
    target_openid: str = ""
    detail: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class StateStoreProtocol(Protocol):
    """Pluggable async storage interface for stateful group-admin data."""

    async def is_group_enabled(
        self, group_openid: str, *, default: bool = True
    ) -> bool: ...

    async def set_group_enabled(self, group_openid: str, enabled: bool) -> None: ...

    async def get_cached_bot_role(self, group_openid: str) -> RoleTier | None: ...

    async def set_cached_bot_role(
        self, group_openid: str, role: RoleTier, *, ttl_seconds: int = 300
    ) -> None: ...

    async def consume_daily_quota(
        self, group_openid: str, action_key: str, limit: int
    ) -> QuotaCheckResult: ...

    async def get_daily_quota_usage(
        self, group_openid: str, action_key: str
    ) -> int: ...

    async def acquire_target_cooldown(
        self,
        group_openid: str,
        target_openid: str,
        action_key: str,
        ttl_seconds: int,
    ) -> bool: ...

    async def append_violation(
        self, record: ViolationRecord, *, window_seconds: int
    ) -> list[ViolationRecord]: ...

    async def list_active_violations(
        self, group_openid: str, member_openid: str, *, window_seconds: int
    ) -> list[ViolationRecord]: ...

    async def clear_violations(self, group_openid: str, member_openid: str) -> int: ...

    async def append_audit(
        self, record: AuditRecord, *, max_records_per_group: int = 500
    ) -> None: ...

    async def query_audits(
        self,
        group_openid: str,
        *,
        limit: int = 20,
        source: AuditSource | None = None,
        action: str | None = None,
    ) -> list[AuditRecord]: ...


__all__ = [
    "AuditRecord",
    "QuotaCheckResult",
    "StateStoreProtocol",
    "ViolationRecord",
]
