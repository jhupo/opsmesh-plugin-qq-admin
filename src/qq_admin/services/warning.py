"""Sliding-window violation tracker (`spam`/`abuse`/`ad`) and escalation ladder."""

from dataclasses import dataclass
import time

from qq_admin.config import QQAdminConfig
from qq_admin.store import StateStoreProtocol, ViolationRecord
from qq_admin.typing import EscalationAction, ViolationType


@dataclass(slots=True, frozen=True)
class WarningEscalationResult:
    """Outcome of recording a violation in the sliding window."""

    active_count: int
    action: EscalationAction
    mute_duration_seconds: int = 0
    kick_with_blacklist: bool = False


class WarningService:
    """Track member violations in a sliding window and compute ladder escalations."""

    def __init__(self, config: QQAdminConfig, store: StateStoreProtocol) -> None:
        self._config = config
        self._store = store

    async def record_violation(
        self,
        *,
        group_openid: str,
        member_openid: str,
        violation_type: ViolationType = ViolationType.OTHER,
        reason: str = "",
        operator_openid: str = "",
    ) -> WarningEscalationResult:
        policy = self._config.warning
        active = await self._store.append_violation(
            ViolationRecord(
                group_openid=group_openid,
                member_openid=member_openid,
                violation_type=violation_type,
                reason=reason,
                operator_openid=operator_openid,
                timestamp=time.time(),
            ),
            window_seconds=policy.window_seconds,
        )
        count = len(active)
        if count >= policy.kick_threshold:
            return WarningEscalationResult(
                active_count=count,
                action=EscalationAction.AUTO_KICK,
                kick_with_blacklist=policy.kick_with_blacklist,
            )
        if count >= policy.mute_threshold:
            return WarningEscalationResult(
                active_count=count,
                action=EscalationAction.AUTO_MUTE,
                mute_duration_seconds=policy.mute_duration_seconds,
            )
        return WarningEscalationResult(
            active_count=count,
            action=EscalationAction.WARN_ONLY,
        )

    async def list_warnings(
        self, group_openid: str, member_openid: str
    ) -> list[ViolationRecord]:
        return await self._store.list_active_violations(
            group_openid,
            member_openid,
            window_seconds=self._config.warning.window_seconds,
        )

    async def clear_warnings(self, group_openid: str, member_openid: str) -> int:
        return await self._store.clear_violations(group_openid, member_openid)


__all__ = ["WarningEscalationResult", "WarningService"]
