"""Lightweight in-memory runtime state and PluginRuntime container."""

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import time
from typing import TYPE_CHECKING, Any

from .config import QQAdminConfig

if TYPE_CHECKING:
    from typesafe_sdk import AsyncTypeSafeClient


@dataclass(frozen=True, slots=True)
class OpLogEntry:
    """Single moderation audit record stored in the in-memory ring buffer."""

    timestamp: datetime
    group_openid: str
    action: str
    target_openid: str
    operator_openid: str
    reason: str
    success: bool


@dataclass(frozen=True, slots=True)
class RecentMessage:
    """Compact group chat message snapshot used as context for moderation."""

    message_id: str
    member_openid: str
    text: str
    timestamp: float


class AdminState:
    """Plain in-memory runtime state with TTL cleanup."""

    def __init__(self, config: QQAdminConfig) -> None:
        self._config = config
        self.lock = asyncio.Lock()
        self.bot_roles: dict[str, tuple[str, float]] = {}
        self.member_roles: dict[tuple[str, str], tuple[str, float]] = {}
        self.sender_refreshed_at: dict[tuple[str, str], float] = {}
        self.disabled_groups: set[str] = set()
        self.exempt_users: dict[str, set[str]] = {
            gid: set(users) for gid, users in config.safeguard.exempt_users.items()
        }
        self.daily_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self.last_mute_at: dict[tuple[str, str], float] = {}
        self.warnings: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        self.recent_messages: dict[str, deque[RecentMessage]] = {}
        self.member_checked_at: dict[tuple[str, str], float] = {}
        self.last_tool_exec: dict[tuple[str, str], float] = {}
        self.op_log: deque[OpLogEntry] = deque(
            maxlen=max(config.logging.max_log_entries, 100)
        )

    @staticmethod
    def today_key() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def get_daily_count(self, group_openid: str, metric: str) -> int:
        return self.daily_counts.get((group_openid, metric, self.today_key()), 0)

    def increment_daily(self, group_openid: str, metric: str) -> int:
        key = (group_openid, metric, self.today_key())
        self.daily_counts[key] += 1
        return self.daily_counts[key]

    def record_op(
        self,
        *,
        group_openid: str,
        action: str,
        target_openid: str,
        operator_openid: str,
        reason: str,
        success: bool,
    ) -> OpLogEntry:
        entry = OpLogEntry(
            timestamp=datetime.now(UTC),
            group_openid=group_openid,
            action=action,
            target_openid=target_openid,
            operator_openid=operator_openid,
            reason=reason,
            success=success,
        )
        self.op_log.append(entry)
        return entry

    def get_op_logs(self, group_openid: str, limit: int) -> list[OpLogEntry]:
        items = [e for e in self.op_log if e.group_openid == group_openid]
        return items[-limit:]

    def count_recent_ops(
        self,
        group_openid: str,
        target_openid: str,
        within_hours: float,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
        return sum(
            1
            for e in self.op_log
            if e.success
            and e.group_openid == group_openid
            and e.target_openid == target_openid
            and e.action in ("warn", "mute", "kick")
            and e.timestamp >= cutoff
        )

    def add_warning(
        self,
        group_openid: str,
        member_openid: str,
        category: str,
        window_seconds: int,
        now: float | None = None,
    ) -> int:
        ts = time.time() if now is None else now
        key = (group_openid, member_openid, category)
        bucket = [t for t in self.warnings[key] if ts - t <= window_seconds]
        bucket.append(ts)
        self.warnings[key] = bucket
        return len(bucket)

    def record_message(
        self,
        group_openid: str,
        message_id: str,
        member_openid: str,
        text: str,
        now: float | None = None,
    ) -> None:
        buf = self.recent_messages.get(group_openid)
        if buf is None:
            buf = deque(maxlen=self._config.auto_moderate.recent_context_size)
            self.recent_messages[group_openid] = buf
        buf.append(
            RecentMessage(
                message_id=message_id,
                member_openid=member_openid,
                text=text[:500],
                timestamp=time.time() if now is None else now,
            )
        )

    def get_recent_messages(
        self, group_openid: str, limit: int = 10
    ) -> list[dict[str, str]]:
        buf = self.recent_messages.get(group_openid)
        if not buf:
            return []
        return [
            {
                "message_id": item.message_id,
                "member_openid": item.member_openid,
                "text": item.text,
            }
            for item in list(buf)[-limit:]
        ]

    def mark_member_checked(
        self, group_openid: str, member_openid: str, now: float | None = None
    ) -> None:
        self.member_checked_at[(group_openid, member_openid)] = (
            time.time() if now is None else now
        )

    def was_member_checked_recently(
        self,
        group_openid: str,
        member_openid: str,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> bool:
        checked = self.member_checked_at.get((group_openid, member_openid), 0.0)
        ts = time.time() if now is None else now
        return checked > 0.0 and (ts - checked) <= ttl_seconds

    def mark_tool_exec(
        self, group_openid: str, action: str, now: float | None = None
    ) -> None:
        self.last_tool_exec[(group_openid, action)] = (
            time.time() if now is None else now
        )

    def was_tool_exec_recently(
        self,
        group_openid: str,
        action: str,
        window_seconds: float = 30.0,
        now: float | None = None,
    ) -> bool:
        executed = self.last_tool_exec.get((group_openid, action), 0.0)
        ts = time.time() if now is None else now
        return executed > 0.0 and (ts - executed) <= window_seconds

    def cleanup(self, now: float | None = None) -> None:
        """Evict expired cache entries and stale daily counters."""
        ts = time.time() if now is None else now
        today = self.today_key()
        for key in list(self.daily_counts.keys()):
            if key[2] != today:
                del self.daily_counts[key]

        role_ttl = max(self._config.auto_moderate.role_cache_ttl_seconds, 60)
        for key in list(self.member_roles.keys()):
            if ts - self.member_roles[key][1] > role_ttl:
                del self.member_roles[key]

        warn_ttl = max(
            self._config.warning.spam_window_seconds,
            self._config.warning.abuse_window_seconds,
            self._config.warning.ad_window_seconds,
            3600,
        )
        for key in list(self.warnings.keys()):
            kept = [t for t in self.warnings[key] if ts - t <= warn_ttl]
            if kept:
                self.warnings[key] = kept
            else:
                del self.warnings[key]

        cooldown_ttl = max(self._config.safeguard.mute_cooldown, 300) * 3
        for key in list(self.last_mute_at.keys()):
            if ts - self.last_mute_at[key] > cooldown_ttl:
                del self.last_mute_at[key]

        for key in list(self.member_checked_at.keys()):
            if ts - self.member_checked_at[key] > 600:
                del self.member_checked_at[key]

        for key in list(self.last_tool_exec.keys()):
            if ts - self.last_tool_exec[key] > 120:
                del self.last_tool_exec[key]


@dataclass(slots=True)
class PluginRuntime:
    """Shared runtime bundle injected into handlers, commands, and agents."""

    config: QQAdminConfig
    state: AdminState
    jev_client: "AsyncTypeSafeClient | None" = None
    jev_http_client: Any | None = None
    owns_jev_client: bool = False
    prompts: dict[str, Any] = field(default_factory=dict)


__all__ = ["AdminState", "OpLogEntry", "PluginRuntime", "RecentMessage"]
