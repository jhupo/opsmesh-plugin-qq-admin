"""Role-aware 8-step safety guardrail module with self-owned SafeguardConfig."""

from dataclasses import dataclass
from datetime import date
import time
from typing import Literal

from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.config import ConfigStore, parse_field_value

from .duration import MAX_QQ_MUTE_SECONDS, MIN_QQ_MUTE_SECONDS
from .escalation import EscalationModule
from .identity import IdentityModule

GuardAction = Literal["warn", "mute", "kick", "ban", "recall"]


class SafeguardConfig(BaseModel):
    """Hard safety limits enforced when the bot operates as a group admin."""

    enabled: bool = True
    max_mute_duration: int = Field(default=3600, ge=60, le=2_592_000)
    mute_cooldown: int = Field(default=300, ge=0)
    daily_mute_limit: int = Field(default=10, ge=1)
    daily_kick_limit: int = Field(default=3, ge=1)
    protected_users: list[str] = Field(default_factory=list)
    exempt_users: list[str] = Field(default_factory=list)
    auto_exempt_admins: bool = True
    kick_require_confirm: bool = True


@dataclass(slots=True)
class PolicyVerdict:
    """Result of evaluating SafeguardModule rules for one moderation action."""

    allowed: bool
    reason: str = ""
    blocked_by: str = ""
    effective_mute_seconds: int | None = None
    escalated_action: str | None = None
    bot_role: str = "member"


class SafeguardModule:
    """Enforces 8-step guardrails for admin bots and bypasses for group owners."""

    def __init__(
        self,
        store: ConfigStore,
        identity: IdentityModule,
        escalation: EscalationModule,
    ) -> None:
        self._store = store
        self._identity = identity
        self._escalation = escalation
        self._daily_date: date = date.today()
        self._daily_counts: dict[tuple[str, str], int] = {}
        self._mute_timestamps: dict[tuple[str, str], float] = {}
        self._verified_members: dict[tuple[str, str], float] = {}

    def config(self, group_id: str | None = None) -> SafeguardConfig:
        raw = self._store.load_section("safeguard", group_id=group_id)
        return SafeguardConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> SafeguardConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(SafeguardConfig, key, raw_value)
        validated = SafeguardConfig.model_validate(current)
        self._store.save_section("safeguard", validated.model_dump(), group_id=group_id)
        return validated

    def add_exempt(self, group_id: str, member_id: str) -> None:
        cfg = self.config(group_id)
        if member_id not in cfg.exempt_users:
            updated = cfg.model_copy(
                update={"exempt_users": [*cfg.exempt_users, member_id]}
            )
            self._store.save_section(
                "safeguard", updated.model_dump(), group_id=group_id
            )

    def remove_exempt(self, group_id: str, member_id: str) -> None:
        cfg = self.config(group_id)
        if member_id in cfg.exempt_users:
            updated = cfg.model_copy(
                update={"exempt_users": [u for u in cfg.exempt_users if u != member_id]}
            )
            self._store.save_section(
                "safeguard", updated.model_dump(), group_id=group_id
            )

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._daily_date:
            self._daily_date = today
            self._daily_counts.clear()

    def daily_count(self, group_id: str, counter: str) -> int:
        self._roll_day()
        return self._daily_counts.get((group_id, counter), 0)

    def daily_counts(self, group_id: str) -> dict[str, int]:
        self._roll_day()
        return {
            "mute": self._daily_counts.get((group_id, "mute"), 0),
            "kick": self._daily_counts.get((group_id, "kick"), 0),
            "approve": self._daily_counts.get((group_id, "approve"), 0),
            "reject": self._daily_counts.get((group_id, "reject"), 0),
        }

    def increment_daily(self, group_id: str, counter: str) -> int:
        self._roll_day()
        key = (group_id, counter)
        self._daily_counts[key] = self._daily_counts.get(key, 0) + 1
        return self._daily_counts[key]

    def record_mute(self, group_id: str, member_id: str) -> None:
        self._mute_timestamps[(group_id, member_id)] = time.monotonic()

    def last_mute_elapsed(self, group_id: str, member_id: str) -> float | None:
        ts = self._mute_timestamps.get((group_id, member_id))
        return None if ts is None else (time.monotonic() - ts)

    def mark_member_verified(self, group_id: str, member_id: str) -> None:
        self._verified_members[(group_id, member_id)] = time.monotonic()

    def is_member_verified(
        self, group_id: str, member_id: str, *, ttl_seconds: float = 300.0
    ) -> bool:
        ts = self._verified_members.get((group_id, member_id))
        return ts is not None and (time.monotonic() - ts) <= ttl_seconds

    def clear_member(self, group_id: str, member_id: str) -> None:
        self._mute_timestamps.pop((group_id, member_id), None)
        self._verified_members.pop((group_id, member_id), None)

    async def check_action(
        self,
        gateway: Gateway,
        group_id: str,
        target_id: str,
        action: GuardAction,
        *,
        mute_seconds: int | None = None,
        require_confirm: bool = False,
    ) -> PolicyVerdict:
        bot_role = await self._identity.bot_role(gateway, group_id)
        if bot_role == "member":
            return PolicyVerdict(
                allowed=False,
                reason="bot is not a group admin or owner",
                blocked_by="bot_not_admin",
                bot_role=bot_role,
            )

        clamped_mute = (
            max(MIN_QQ_MUTE_SECONDS, min(mute_seconds, MAX_QQ_MUTE_SECONDS))
            if mute_seconds is not None
            else None
        )
        cfg = self.config(group_id)
        if bot_role == "owner" or not cfg.enabled:
            return PolicyVerdict(
                allowed=True,
                effective_mute_seconds=clamped_mute,
                bot_role=bot_role,
            )

        id_cfg = self._identity.config(group_id)
        if target_id in cfg.protected_users:
            return PolicyVerdict(
                allowed=False,
                reason="target is in protected_users",
                blocked_by="protected_users",
                bot_role=bot_role,
            )
        if target_id in cfg.exempt_users:
            return PolicyVerdict(
                allowed=False,
                reason="target is in group exempt_users",
                blocked_by="exempt_users",
                bot_role=bot_role,
            )
        if target_id in id_cfg.admins:
            return PolicyVerdict(
                allowed=False,
                reason="target is a configured global admin",
                blocked_by="admins",
                bot_role=bot_role,
            )
        if cfg.auto_exempt_admins:
            target_role = await self._identity.member_role(gateway, group_id, target_id)
            if target_role in {"owner", "admin"}:
                return PolicyVerdict(
                    allowed=False,
                    reason=f"target is group {target_role}",
                    blocked_by="auto_exempt_admins",
                    bot_role=bot_role,
                )

        if action == "mute":
            elapsed = self.last_mute_elapsed(group_id, target_id)
            if elapsed is not None and elapsed < cfg.mute_cooldown:
                remaining = int(cfg.mute_cooldown - elapsed)
                return PolicyVerdict(
                    allowed=False,
                    reason=f"mute cooldown active ({remaining}s remaining)",
                    blocked_by="mute_cooldown",
                    bot_role=bot_role,
                )
            if self.daily_count(group_id, "mute") >= cfg.daily_mute_limit:
                return PolicyVerdict(
                    allowed=False,
                    reason="daily mute limit reached",
                    blocked_by="daily_mute_limit",
                    bot_role=bot_role,
                )
            if clamped_mute is not None:
                clamped_mute = min(clamped_mute, cfg.max_mute_duration)

        if action in {"kick", "ban"}:
            if self.daily_count(group_id, "kick") >= cfg.daily_kick_limit:
                return PolicyVerdict(
                    allowed=False,
                    reason="daily kick limit reached",
                    blocked_by="daily_kick_limit",
                    bot_role=bot_role,
                )
            if (
                action == "kick"
                and require_confirm
                and cfg.kick_require_confirm
                and not self.is_member_verified(group_id, target_id)
            ):
                return PolicyVerdict(
                    allowed=False,
                    reason="kick requires calling get_member first",
                    blocked_by="kick_require_confirm",
                    bot_role=bot_role,
                )

        escalated_action: str | None = None
        step = self._escalation.resolve_step(group_id, target_id)
        if step is not None:
            escalated_action = step.action
            if step.action == "mute" and clamped_mute is not None:
                clamped_mute = min(
                    max(clamped_mute, step.mute_seconds),
                    cfg.max_mute_duration,
                )

        return PolicyVerdict(
            allowed=True,
            effective_mute_seconds=clamped_mute,
            escalated_action=escalated_action,
            bot_role=bot_role,
        )


__all__ = [
    "GuardAction",
    "PolicyVerdict",
    "SafeguardConfig",
    "SafeguardModule",
]
