"""GroupModerator: single direct executor for Official QQ Bot v2 write actions."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from qq import Gateway, SetMemberMuteState

from qq_admin.config import AdminConfig
from qq_admin.resources import PromptCatalog
from qq_admin.state import GroupStateStore

from .duration import MuteDuration, format_duration, parse_duration
from .policy import SafeguardPolicy


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Outcome of a single moderation operation."""

    succeeded: bool
    action: str
    message: str
    blocked_by: str = ""
    escalated_to: str = ""


class GroupModerator:
    """Executes guarded Official QQ v2 moderation actions and records audits."""

    def __init__(
        self,
        config: AdminConfig,
        state: GroupStateStore,
        policy: SafeguardPolicy,
        catalog: PromptCatalog,
    ) -> None:
        self.config = config
        self.state = state
        self.policy = policy
        self.catalog = catalog

    def _warning_window(
        self, category: Literal["spam", "abuse", "ad"]
    ) -> tuple[int, int]:
        wc = self.config.warning
        if category == "spam":
            return wc.spam_threshold, wc.spam_window_seconds
        if category == "ad":
            return wc.ad_threshold, wc.ad_window_seconds
        return wc.abuse_threshold, wc.abuse_window_seconds

    def _blocked_outcome(self, action: str, step: str, reason: str) -> ActionOutcome:
        return ActionOutcome(
            succeeded=False,
            action=action,
            message=self.catalog.format_fallback("action_blocked", reason=reason),
            blocked_by=step,
        )

    def _failed_outcome(self, action: str, reason: str) -> ActionOutcome:
        return ActionOutcome(
            succeeded=False,
            action=action,
            message=self.catalog.format_fallback("action_failed", reason=reason),
        )

    async def warn(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        category: Literal["spam", "abuse", "ad"],
        reason: str,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Record a sliding-window warning and audit entry."""
        async with self.state.lock:
            verdict = await self.policy.verify_action(
                gateway, group_id, member_id, "warn"
            )
            if not verdict.allowed:
                return self._blocked_outcome("warn", verdict.step, verdict.reason)

            extra = ""
            if self.config.warning.enabled:
                threshold, window = self._warning_window(category)
                count = self.state.record_warning(group_id, member_id, category, window)
                if count >= threshold:
                    extra = self.catalog.format_fallback(
                        "warn_threshold_hint", current=count, threshold=threshold
                    )

            self.state.record_audit(
                group_id=group_id,
                action="warn",
                target_id=member_id,
                operator_id=operator_id,
                reason=f"[{category}] {reason}",
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="warn",
                message=self.catalog.format_fallback(
                    "warn_done",
                    member_id=member_id,
                    category=category,
                    reason=reason,
                    extra=extra,
                ),
            )

    async def mute(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        duration: MuteDuration,
        reason: str = "policy",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Mute a member via Official QQ v2 set_group_members_mute."""
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            return self._failed_outcome("mute", str(exc))

        async with self.state.lock:
            verdict = await self.policy.verify_action(
                gateway, group_id, member_id, "mute", duration=seconds
            )
            if not verdict.allowed:
                return self._blocked_outcome("mute", verdict.step, verdict.reason)

            effective = verdict.adjusted_duration or seconds
            state_item = SetMemberMuteState(
                member_openid=member_id,
                op="add",
                mute_expire_at=timedelta(seconds=effective),
            )
            try:
                await gateway.set_group_members_mute(group_id, [state_item])
            except Exception as exc:
                self.state.record_audit(
                    group_id=group_id,
                    action="mute",
                    target_id=member_id,
                    operator_id=operator_id,
                    reason=reason,
                    succeeded=False,
                )
                return self._failed_outcome("mute", str(exc))

            self.state.increment_daily(group_id, "mute")
            self.state.mark_muted(group_id, member_id)
            label = format_duration(effective)
            self.state.record_audit(
                group_id=group_id,
                action="mute",
                target_id=member_id,
                operator_id=operator_id,
                reason=f"{label}: {reason}",
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="mute",
                message=self.catalog.format_fallback(
                    "mute_done", member_id=member_id, duration=label, reason=reason
                ),
                escalated_to=verdict.escalated_action or "",
            )

    async def unmute(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Lift a member's mute immediately."""
        async with self.state.lock:
            if await self.policy.bot_role(gateway, group_id) not in ("owner", "admin"):
                return self._blocked_outcome(
                    "unmute",
                    "bot_role",
                    self.catalog.format_fallback("bot_not_admin"),
                )
            try:
                await gateway.set_group_members_mute(
                    group_id, [SetMemberMuteState(member_openid=member_id, op="del")]
                )
            except Exception as exc:
                return self._failed_outcome("unmute", str(exc))

            self.state.record_audit(
                group_id=group_id,
                action="unmute",
                target_id=member_id,
                operator_id=operator_id,
                reason="unmute",
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="unmute",
                message=self.catalog.format_fallback(
                    "unmute_done", member_id=member_id
                ),
            )

    async def kick(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        reason: str = "policy",
        blacklist: bool = False,
        operator_id: str = "bot",
        require_confirm: bool = False,
    ) -> ActionOutcome:
        """Remove a member via Official QQ v2 batch_remove_group_members."""
        async with self.state.lock:
            verdict = await self.policy.verify_action(
                gateway,
                group_id,
                member_id,
                "kick",
                require_confirm=require_confirm,
            )
            if not verdict.allowed:
                return self._blocked_outcome("kick", verdict.step, verdict.reason)

            ban_flag = blacklist or verdict.escalate_blacklist
            try:
                await gateway.batch_remove_group_members(
                    group_id, [member_id], add_to_member_blacklist=ban_flag
                )
            except Exception as exc:
                self.state.record_audit(
                    group_id=group_id,
                    action="kick",
                    target_id=member_id,
                    operator_id=operator_id,
                    reason=reason,
                    succeeded=False,
                )
                return self._failed_outcome("kick", str(exc))

            self.state.increment_daily(group_id, "kick")
            self.state.record_audit(
                group_id=group_id,
                action="kick",
                target_id=member_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="kick",
                message=self.catalog.format_fallback(
                    "kick_done",
                    member_id=member_id,
                    blacklist=str(ban_flag).lower(),
                    reason=reason,
                ),
            )

    async def ban(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        reason: str = "blacklist",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Add a member to the Official QQ v2 group blacklist."""
        async with self.state.lock:
            verdict = await self.policy.verify_action(
                gateway, group_id, member_id, "ban"
            )
            if not verdict.allowed:
                return self._blocked_outcome("ban", verdict.step, verdict.reason)
            try:
                res = await gateway.post_group_member_blacklist(
                    group_id, op="add", member_openids=[member_id]
                )
            except Exception as exc:
                return self._failed_outcome("ban", str(exc))
            if member_id in res.fail_openids:
                return self._failed_outcome("ban", "platform rejected openid")

            self.state.record_audit(
                group_id=group_id,
                action="ban",
                target_id=member_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="ban",
                message=self.catalog.format_fallback("ban_done", member_id=member_id),
            )

    async def unban(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Remove a member from the Official QQ v2 group blacklist."""
        async with self.state.lock:
            if await self.policy.bot_role(gateway, group_id) not in ("owner", "admin"):
                return self._blocked_outcome(
                    "unban",
                    "bot_role",
                    self.catalog.format_fallback("bot_not_admin"),
                )
            try:
                res = await gateway.post_group_member_blacklist(
                    group_id, op="del", member_openids=[member_id]
                )
            except Exception as exc:
                return self._failed_outcome("unban", str(exc))
            if member_id in res.fail_openids:
                return self._failed_outcome("unban", "platform rejected openid")

            self.state.record_audit(
                group_id=group_id,
                action="unban",
                target_id=member_id,
                operator_id=operator_id,
                reason="unban",
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="unban",
                message=self.catalog.format_fallback("unban_done", member_id=member_id),
            )

    async def recall(
        self,
        gateway: Gateway,
        group_id: str,
        message_id: str,
        *,
        target_id: str = "",
        reason: str = "policy",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Recall a violating message via Official QQ v2 delete_group_message."""
        async with self.state.lock:
            if await self.policy.bot_role(gateway, group_id) not in ("owner", "admin"):
                return self._blocked_outcome(
                    "recall",
                    "bot_role",
                    self.catalog.format_fallback("bot_not_admin"),
                )
            try:
                await gateway.delete_group_message(group_id, message_id)
            except Exception as exc:
                return self._failed_outcome("recall", str(exc))

            self.state.record_audit(
                group_id=group_id,
                action="recall",
                target_id=target_id or message_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="recall",
                message=self.catalog.format_fallback(
                    "recall_done", message_id=message_id
                ),
            )

    async def apply_ladder(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        message_id: str,
        category: Literal["spam", "abuse", "ad"],
        tier: Literal["warn", "enforce", "severe"],
        reason: str,
    ) -> list[ActionOutcome]:
        """Direct Jev-to-escalation execution when DecisionPlanner is disabled."""
        outcomes: list[ActionOutcome] = []
        if message_id and tier in ("enforce", "severe"):
            outcomes.append(
                await self.recall(
                    gateway,
                    group_id,
                    message_id,
                    target_id=member_id,
                    reason=reason,
                )
            )
        if tier == "severe":
            outcomes.append(
                await self.kick(
                    gateway, group_id, member_id, reason=reason, blacklist=True
                )
            )
            return outcomes

        rule = self.policy.matched_escalation(group_id, member_id)
        if tier == "warn" and rule is None:
            outcomes.append(
                await self.warn(
                    gateway, group_id, member_id, category=category, reason=reason
                )
            )
            return outcomes
        if rule is not None and rule.action == "kick":
            outcomes.append(
                await self.kick(
                    gateway,
                    group_id,
                    member_id,
                    reason=reason,
                    blacklist=rule.blacklist,
                )
            )
            return outcomes

        seconds = rule.mute_seconds if rule is not None else 600
        outcomes.append(
            await self.mute(
                gateway, group_id, member_id, duration=seconds, reason=reason
            )
        )
        return outcomes


__all__ = ["ActionOutcome", "GroupModerator"]
