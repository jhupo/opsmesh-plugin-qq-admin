"""In-memory runtime state store with automatic TTL eviction."""

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time

from .config import AdminConfig


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Single moderation audit log entry."""

    timestamp: datetime
    group_id: str
    action: str
    target_id: str
    operator_id: str
    reason: str
    succeeded: bool


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    """Compact message entry stored in the per-group sliding context window."""

    message_id: str
    member_id: str
    text: str
    timestamp: float


class GroupStateStore:
    """Cohesive in-memory store for role caches, quotas, warnings, and audit logs."""

    def __init__(self, config: AdminConfig) -> None:
        self._config = config
        self.lock = asyncio.Lock()
        self.bot_roles: dict[str, tuple[str, float]] = {}
        self.member_roles: dict[tuple[str, str], tuple[str, float]] = {}
        self.sender_checked_at: dict[tuple[str, str], float] = {}
        self.paused_groups: set[str] = set()
        self.exempt_members: dict[str, set[str]] = {
            gid: set(members) for gid, members in config.safeguard.exempt_users.items()
        }
        self._daily_counters: dict[tuple[str, str, str], int] = defaultdict(int)
        self._last_muted_at: dict[tuple[str, str], float] = {}
        self._warnings: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        self._recent_messages: dict[str, deque[MessageSnapshot]] = {}
        self._member_verified_at: dict[tuple[str, str], float] = {}
        self._audit_log: deque[AuditRecord] = deque(
            maxlen=max(config.logging.max_log_entries, 100)
        )

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def daily_count(self, group_id: str, metric: str) -> int:
        return self._daily_counters.get((group_id, metric, self._today()), 0)

    def increment_daily(self, group_id: str, metric: str) -> int:
        key = (group_id, metric, self._today())
        self._daily_counters[key] += 1
        return self._daily_counters[key]

    def cooldown_remaining(
        self, group_id: str, member_id: str, cooldown_seconds: int
    ) -> int:
        if cooldown_seconds <= 0:
            return 0
        last = self._last_muted_at.get((group_id, member_id), 0.0)
        if last <= 0.0:
            return 0
        elapsed = time.time() - last
        return int(cooldown_seconds - elapsed) if elapsed < cooldown_seconds else 0

    def mark_muted(self, group_id: str, member_id: str) -> None:
        self._last_muted_at[(group_id, member_id)] = time.time()

    def record_audit(
        self,
        *,
        group_id: str,
        action: str,
        target_id: str,
        operator_id: str,
        reason: str,
        succeeded: bool,
    ) -> AuditRecord:
        entry = AuditRecord(
            timestamp=datetime.now(UTC),
            group_id=group_id,
            action=action,
            target_id=target_id,
            operator_id=operator_id,
            reason=reason,
            succeeded=succeeded,
        )
        self._audit_log.append(entry)
        return entry

    def recent_audits(self, group_id: str, limit: int) -> list[AuditRecord]:
        matched = [e for e in self._audit_log if e.group_id == group_id]
        return matched[-limit:]

    def count_violations(
        self, group_id: str, target_id: str, within_hours: float
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
        return sum(
            1
            for e in self._audit_log
            if e.succeeded
            and e.group_id == group_id
            and e.target_id == target_id
            and e.action in ("warn", "mute", "kick")
            and e.timestamp >= cutoff
        )

    def record_warning(
        self,
        group_id: str,
        member_id: str,
        category: str,
        window_seconds: int,
    ) -> int:
        now = time.time()
        key = (group_id, member_id, category)
        active = [ts for ts in self._warnings[key] if now - ts <= window_seconds]
        active.append(now)
        self._warnings[key] = active
        return len(active)

    def append_message(
        self, group_id: str, message_id: str, member_id: str, text: str
    ) -> None:
        buf = self._recent_messages.get(group_id)
        if buf is None:
            buf = deque(maxlen=self._config.moderation.recent_context_size)
            self._recent_messages[group_id] = buf
        buf.append(
            MessageSnapshot(
                message_id=message_id,
                member_id=member_id,
                text=text[:500],
                timestamp=time.time(),
            )
        )

    def recent_context(self, group_id: str, limit: int = 8) -> list[dict[str, str]]:
        buf = self._recent_messages.get(group_id)
        if not buf:
            return []
        return [
            {
                "message_id": item.message_id,
                "member_id": item.member_id,
                "text": item.text,
            }
            for item in list(buf)[-limit:]
        ]

    def mark_member_verified(self, group_id: str, member_id: str) -> None:
        self._member_verified_at[(group_id, member_id)] = time.time()

    def is_member_verified(
        self, group_id: str, member_id: str, ttl_seconds: float = 300.0
    ) -> bool:
        ts = self._member_verified_at.get((group_id, member_id), 0.0)
        return ts > 0.0 and (time.time() - ts) <= ttl_seconds

    def evict_expired(self, now: float | None = None) -> None:
        """Remove stale daily counters, expired warnings, and old cache entries."""
        ts = time.time() if now is None else now
        today = self._today()
        for key in list(self._daily_counters.keys()):
            if key[2] != today:
                del self._daily_counters[key]

        role_ttl = max(self._config.identity.role_cache_ttl_seconds, 60)
        for key in list(self.member_roles.keys()):
            if ts - self.member_roles[key][1] > role_ttl:
                del self.member_roles[key]

        warn_ttl = max(
            self._config.warning.spam_window_seconds,
            self._config.warning.abuse_window_seconds,
            self._config.warning.ad_window_seconds,
            3600,
        )
        for key in list(self._warnings.keys()):
            kept = [t for t in self._warnings[key] if ts - t <= warn_ttl]
            if kept:
                self._warnings[key] = kept
            else:
                del self._warnings[key]

        cooldown_ttl = max(self._config.safeguard.mute_cooldown, 300) * 3
        for key in list(self._last_muted_at.keys()):
            if ts - self._last_muted_at[key] > cooldown_ttl:
                del self._last_muted_at[key]

        for key in list(self._member_verified_at.keys()):
            if ts - self._member_verified_at[key] > 600:
                del self._member_verified_at[key]


__all__ = ["AuditRecord", "GroupStateStore", "MessageSnapshot"]
