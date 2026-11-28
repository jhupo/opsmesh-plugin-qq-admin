"""Audit logging module with self-owned AuditConfig."""

from collections import deque
from dataclasses import dataclass, field
import time

from pydantic import BaseModel, Field

from qq_admin.config import ConfigStore, parse_field_value


class AuditConfig(BaseModel):
    """In-memory audit log retention settings."""

    enabled: bool = Field(default=True, description="Enable audit log recording.")
    max_entries: int = Field(default=2000, ge=100)
    default_lines: int = Field(default=10, ge=1, le=100)


@dataclass(slots=True)
class AuditRecord:
    """Single moderation or group lifecycle audit log entry."""

    group_id: str
    action: str
    target_id: str
    operator_id: str
    reason: str
    succeeded: bool
    timestamp: float = field(default_factory=time.time)


class AuditModule:
    """Records and queries per-group moderation audit entries."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._logs: dict[str, deque[AuditRecord]] = {}

    def config(self, group_id: str | None = None) -> AuditConfig:
        raw = self._store.load_section("audit", group_id=group_id)
        return AuditConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> AuditConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(AuditConfig, key, raw_value)
        validated = AuditConfig.model_validate(current)
        self._store.save_section("audit", validated.model_dump(), group_id=group_id)
        return validated

    def record(self, entry: AuditRecord) -> None:
        cfg = self.config(entry.group_id)
        if not cfg.enabled:
            return
        bucket = self._logs.get(entry.group_id)
        if bucket is None or bucket.maxlen != cfg.max_entries:
            bucket = deque(bucket or (), maxlen=cfg.max_entries)
            self._logs[entry.group_id] = bucket
        bucket.append(entry)

    def recent_logs(self, group_id: str, limit: int | None = None) -> list[AuditRecord]:
        cfg = self.config(group_id)
        count = max(1, limit or cfg.default_lines)
        bucket = self._logs.get(group_id)
        if not bucket:
            return []
        return list(bucket)[-count:]

    def count_member_actions(
        self,
        group_id: str,
        member_id: str,
        *,
        within_hours: float,
        actions: set[str] | None = None,
    ) -> int:
        cutoff = time.time() - within_hours * 3600.0
        allowed = actions or {"warn", "mute", "kick", "ban"}
        bucket = self._logs.get(group_id)
        if not bucket:
            return 0
        return sum(
            1
            for rec in bucket
            if rec.succeeded
            and rec.target_id == member_id
            and rec.action in allowed
            and rec.timestamp >= cutoff
        )

    def forget_group(self, group_id: str) -> None:
        self._logs.pop(group_id, None)


__all__ = ["AuditConfig", "AuditModule", "AuditRecord"]
