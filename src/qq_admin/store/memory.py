"""Default zero-dependency `InMemoryStateStore` with optional JSON snapshot."""

from collections import deque
from datetime import UTC, datetime
import json
from pathlib import Path
import time

from qq_admin.typing import AuditSource, RoleTier

from .protocol import AuditRecord, QuotaCheckResult, ViolationRecord


class InMemoryStateStore:
    """In-memory implementation of StateStoreProtocol with optional JSON snapshot."""

    def __init__(self, *, snapshot_path: str | Path | None = None) -> None:
        self._snapshot_path: Path | None = (
            Path(snapshot_path) if snapshot_path is not None else None
        )
        self._group_switches: dict[str, bool] = {}
        self._bot_roles: dict[str, tuple[RoleTier, float]] = {}
        self._daily_quotas: dict[tuple[str, str, str], int] = {}
        self._cooldowns: dict[tuple[str, str, str], float] = {}
        self._violations: dict[tuple[str, str], list[ViolationRecord]] = {}
        self._audits: dict[str, deque[AuditRecord]] = {}
        if self._snapshot_path and self._snapshot_path.exists():
            self._load_snapshot()

    @staticmethod
    def _today_key() -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d")

    async def is_group_enabled(
        self, group_openid: str, *, default: bool = True
    ) -> bool:
        return self._group_switches.get(group_openid, default)

    async def set_group_enabled(self, group_openid: str, enabled: bool) -> None:
        self._group_switches[group_openid] = enabled
        self._save_snapshot()

    async def get_cached_bot_role(self, group_openid: str) -> RoleTier | None:
        entry = self._bot_roles.get(group_openid)
        if entry is None:
            return None
        role, expires_at = entry
        if time.monotonic() >= expires_at:
            self._bot_roles.pop(group_openid, None)
            return None
        return role

    async def set_cached_bot_role(
        self, group_openid: str, role: RoleTier, *, ttl_seconds: int = 300
    ) -> None:
        self._bot_roles[group_openid] = (role, time.monotonic() + ttl_seconds)

    async def consume_daily_quota(
        self, group_openid: str, action_key: str, limit: int
    ) -> QuotaCheckResult:
        key = (group_openid, action_key, self._today_key())
        used = self._daily_quotas.get(key, 0)
        if used >= limit:
            return QuotaCheckResult(allowed=False, used=used, limit=limit)
        used += 1
        self._daily_quotas[key] = used
        return QuotaCheckResult(allowed=True, used=used, limit=limit)

    async def get_daily_quota_usage(self, group_openid: str, action_key: str) -> int:
        return self._daily_quotas.get((group_openid, action_key, self._today_key()), 0)

    async def acquire_target_cooldown(
        self,
        group_openid: str,
        target_openid: str,
        action_key: str,
        ttl_seconds: int,
    ) -> bool:
        if ttl_seconds <= 0:
            return True
        now = time.monotonic()
        key = (group_openid, target_openid, action_key)
        expires_at = self._cooldowns.get(key, 0.0)
        if now < expires_at:
            return False
        self._cooldowns[key] = now + ttl_seconds
        return True

    async def append_violation(
        self, record: ViolationRecord, *, window_seconds: int
    ) -> list[ViolationRecord]:
        key = (record.group_openid, record.member_openid)
        cutoff = record.timestamp - window_seconds
        active = [r for r in self._violations.get(key, []) if r.timestamp >= cutoff]
        active.append(record)
        self._violations[key] = active
        self._save_snapshot()
        return list(active)

    async def list_active_violations(
        self, group_openid: str, member_openid: str, *, window_seconds: int
    ) -> list[ViolationRecord]:
        key = (group_openid, member_openid)
        cutoff = time.time() - window_seconds
        active = [r for r in self._violations.get(key, []) if r.timestamp >= cutoff]
        self._violations[key] = active
        return list(active)

    async def clear_violations(self, group_openid: str, member_openid: str) -> int:
        removed = len(self._violations.pop((group_openid, member_openid), []))
        if removed:
            self._save_snapshot()
        return removed

    async def append_audit(
        self, record: AuditRecord, *, max_records_per_group: int = 500
    ) -> None:
        buf = self._audits.get(record.group_openid)
        if buf is None or buf.maxlen != max_records_per_group:
            buf = deque(buf or (), maxlen=max_records_per_group)
            self._audits[record.group_openid] = buf
        buf.append(record)
        self._save_snapshot()

    async def query_audits(
        self,
        group_openid: str,
        *,
        limit: int = 20,
        source: AuditSource | None = None,
        action: str | None = None,
    ) -> list[AuditRecord]:
        records = list(reversed(self._audits.get(group_openid, ())))
        if source is not None:
            records = [r for r in records if r.source == source]
        if action is not None:
            records = [r for r in records if r.action == action]
        return records[: max(limit, 0)]

    def _save_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        payload = {
            "group_switches": self._group_switches,
            "violations": {
                f"{gid}:{mid}": [r.model_dump(mode="json") for r in items]
                for (gid, mid), items in self._violations.items()
            },
            "audits": {
                gid: [r.model_dump(mode="json") for r in buf]
                for gid, buf in self._audits.items()
            },
        }
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        raw = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        self._group_switches = dict(raw.get("group_switches") or {})
        for composite, items in (raw.get("violations") or {}).items():
            if ":" in composite:
                gid, mid = composite.split(":", 1)
                self._violations[(gid, mid)] = [
                    ViolationRecord.model_validate(x) for x in items
                ]
        for gid, items in (raw.get("audits") or {}).items():
            self._audits[gid] = deque(
                (AuditRecord.model_validate(x) for x in items), maxlen=500
            )


__all__ = ["InMemoryStateStore"]
