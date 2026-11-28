"""Role-aware safety guardrail module with self-owned SafeguardConfig."""

from dataclasses import dataclass
from datetime import date
import time
from typing import Literal

from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.store import ConfigStore, parse_field_value

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


def _block(blocked_by: str, reason: str, bot_role: str) -> PolicyVerdict:
    return PolicyVerdict(
        allowed=False, reason=reason, blocked_by=blocked_by, bot_role=bot_role
    )


class SafeguardModule:
    """Enforces composed guardrail checks for admin bots; bypassed for group owners."""

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
            name: self._daily_counts.get((group_id, name), 0)
            for name in ("mute", "kick", "approve", "reject")
        }

    def increment_daily(self, group_id: str, counter: str) -> int:
        self._roll_day()
        key = (group_id, counter)
        self._daily_counts[key] = self._daily_counts.get(key, 0) + 1
        return self._daily_counts[key]

    def record_mute(self, group_id: str, member_id: str) -> None:
        self._mute_timestamps[(group_id, member_id)] = time.monotonic()

    def mark_member_verified(self, group_id: str, member_id: str) -> None:
        self._verified_members[(group_id, member_id)] = time.monotonic()

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
        """Run protection, action-specific quotas, and escalation checks."""
        bot_role = await self._identity.bot_role(gateway, group_id)
        if bot_role == "member":
            return _block(
                "bot_not_admin", "bot is not a group admin or owner", bot_role
            )

        clamped = (
            max(MIN_QQ_MUTE_SECONDS, min(mute_seconds, MAX_QQ_MUTE_SECONDS))
            if mute_seconds is not None
            else None
        )
        cfg = self.config(group_id)
        if bot_role == "owner" or not cfg.enabled:
            return PolicyVerdict(
                allowed=True, effective_mute_seconds=clamped, bot_role=bot_role
            )

        if blocked := await self._check_protection(
            gateway, group_id, target_id, cfg, bot_role
        ):
            return blocked

        if action == "mute":
            blocked, clamped = self._check_mute_rules(
                group_id, target_id, clamped, cfg, bot_role
            )
            if blocked:
                return blocked
        elif action in {"kick", "ban"}:
            if blocked := self._check_kick_rules(
                group_id, target_id, action, require_confirm, cfg, bot_role
            ):
                return blocked

        escalated, clamped = self._apply_escalation(group_id, target_id, clamped, cfg)
        return PolicyVerdict(
            allowed=True,
            effective_mute_seconds=clamped,
            escalated_action=escalated,
            bot_role=bot_role,
        )

    async def _check_protection(
        self,
        gateway: Gateway,
        group_id: str,
        target_id: str,
        cfg: SafeguardConfig,
        bot_role: str,
    ) -> PolicyVerdict | None:
        if target_id in cfg.protected_users:
            return _block("protected_users", "target is in protected_users", bot_role)
        if target_id in cfg.exempt_users:
            return _block("exempt_users", "target is in group exempt_users", bot_role)
        if cfg.auto_exempt_admins and await self._identity.is_admin(
            gateway, group_id, target_id
        ):
            return _block("auto_exempt_admins", "target is an admin or owner", bot_role)
        return None

    def _check_mute_rules(
        self,
        group_id: str,
        target_id: str,
        mute_seconds: int | None,
        cfg: SafeguardConfig,
        bot_role: str,
    ) -> tuple[PolicyVerdict | None, int | None]:
        ts = self._mute_timestamps.get((group_id, target_id))
        if ts is not None:
            elapsed = time.monotonic() - ts
            if elapsed < cfg.mute_cooldown:
                remaining = int(cfg.mute_cooldown - elapsed)
                return (
                    _block(
                        "mute_cooldown", f"mute cooldown ({remaining}s left)", bot_role
                    ),
                    mute_seconds,
                )
        if self.daily_count(group_id, "mute") >= cfg.daily_mute_limit:
            return _block(
                "daily_mute_limit", "daily mute limit reached", bot_role
            ), mute_seconds
        capped = (
            min(mute_seconds, cfg.max_mute_duration)
            if mute_seconds is not None
            else None
        )
        return None, capped

    def _check_kick_rules(
        self,
        group_id: str,
        target_id: str,
        action: str,
        require_confirm: bool,
        cfg: SafeguardConfig,
        bot_role: str,
    ) -> PolicyVerdict | None:
        if self.daily_count(group_id, "kick") >= cfg.daily_kick_limit:
            return _block("daily_kick_limit", "daily kick limit reached", bot_role)
        verified_at = self._verified_members.get((group_id, target_id))
        is_verified = (
            verified_at is not None and (time.monotonic() - verified_at) <= 300.0
        )
        if (
            action == "kick"
            and require_confirm
            and cfg.kick_require_confirm
            and not is_verified
        ):
            return _block(
                "kick_require_confirm", "call get_member before kicking", bot_role
            )
        return None

    def _apply_escalation(
        self,
        group_id: str,
        target_id: str,
        mute_seconds: int | None,
        cfg: SafeguardConfig,
    ) -> tuple[str | None, int | None]:
        step = self._escalation.resolve_step(group_id, target_id)
        if step is None:
            return None, mute_seconds
        if step.action == "mute" and mute_seconds is not None:
            mute_seconds = min(
                max(mute_seconds, step.mute_seconds), cfg.max_mute_duration
            )
        return step.action, mute_seconds


__all__ = ["GuardAction", "PolicyVerdict", "SafeguardConfig", "SafeguardModule"]
