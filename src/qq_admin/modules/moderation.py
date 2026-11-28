"""Automatic moderation module: Jev SafetyReport, dual agents, and QQ v2 actions."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from qq import Gateway, SetMemberMuteState

from qq_admin.models import DecisionOutcome, ReplySpec, SafetyReport, TurnContext
from qq_admin.store import ConfigStore, parse_field_value

from .audit import AuditRecord
from .duration import format_duration, parse_duration

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager

WarningCategory = Literal["spam", "abuse", "ad"]


class ModerationConfig(BaseModel):
    """Automatic moderation switches and calibrated Jev thresholds."""

    enabled: bool = True
    stop_on_violation: bool = True
    allow_admin_nl_control: bool = True
    welcome_new_members: bool = False
    enable_image_review: bool = True
    enable_action_guardrail: bool = True
    max_images: int = Field(default=4, ge=1, le=8)
    injection_block_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    warn_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    enforce_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    action_validity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    output_safety_threshold: float = Field(default=0.80, ge=0.0, le=1.0)


@dataclass(slots=True)
class ActionOutcome:
    """Outcome of one moderation action."""

    succeeded: bool
    action: str
    message: str
    blocked_by: str = ""


class ModerationModule:
    """Moderates group messages and executes Official QQ v2 admin actions."""

    def __init__(self, store: ConfigStore, manager: "ServiceManager") -> None:
        self._store = store
        self._manager = manager

    def config(self, group_id: str | None = None) -> ModerationConfig:
        raw = self._store.load_section("moderation", group_id=group_id)
        return ModerationConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> ModerationConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(ModerationConfig, key, raw_value)
        validated = ModerationConfig.model_validate(current)
        self._store.save_section(
            "moderation", validated.model_dump(), group_id=group_id
        )
        return validated

    async def assess(
        self,
        group_id: str,
        *,
        text: str = "",
        images: list[bytes] | None = None,
        urls: list[str] | None = None,
    ) -> SafetyReport:
        """Run stateless Jev.execute() on text, images, text+images, or links."""
        cfg = self.config(group_id)
        selected_images = (
            (images or [])[: cfg.max_images] if cfg.enable_image_review else None
        )
        try:
            return await self._manager.jev.execute(
                text=text, images=selected_images, urls=urls
            )
        except Exception:
            return SafetyReport()

    async def moderate_message(
        self,
        gateway: Gateway,
        *,
        group_id: str,
        member_id: str,
        message_id: str,
        text: str,
        sender_role: str,
        images: list[bytes] | None = None,
        urls: list[str] | None = None,
    ) -> tuple[bool, str | None]:
        """Jev SafetyReport -> DecisionAgent -> ReplyAgent; silent on safe chat."""
        cfg = self.config(group_id)
        if not cfg.enabled:
            return False, None

        report = await self.assess(group_id, text=text, images=images, urls=urls)
        if report.prompt_injection >= cfg.injection_block_threshold:
            return False, None
        if not report.is_flagged(cfg.warn_confidence):
            return False, None

        bot_role = await self._manager.identity.bot_role(gateway, group_id)
        if not self._manager.decision_agent.is_ready:
            return await self._enforce_without_agent(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=message_id,
                bot_role=bot_role,
                report=report,
            )

        summary = report.summary(cfg.warn_confidence)
        turn = TurnContext(
            gateway=gateway,
            manager=self._manager,
            group_id=group_id,
            member_id=member_id,
            message_id=message_id,
            message_text=text,
            bot_role=bot_role,
            sender_role=sender_role,
            mode="auto_moderate",
            jev_summary=summary,
        )
        prompt = (
            f"message_id={message_id}\nmember_id={member_id} (role={sender_role})\n"
            f"content={text}\nimages={len(images or [])}\nurls={urls or []}\n"
            f"jev={summary}"
        )
        decision = await self._manager.decision_agent.execute(prompt, context=turn)
        return decision.action_taken, await self._reply_for(turn, decision)

    async def follow_admin_instruction(
        self,
        gateway: Gateway,
        *,
        group_id: str,
        member_id: str,
        message_id: str,
        text: str,
        sender_role: str,
    ) -> tuple[bool, str | None]:
        """Execute an owner/admin @mention instruction through DecisionAgent."""
        cfg = self.config(group_id)
        if not cfg.allow_admin_nl_control or not self._manager.decision_agent.is_ready:
            return False, None
        turn = TurnContext(
            gateway=gateway,
            manager=self._manager,
            group_id=group_id,
            member_id=member_id,
            message_id=message_id,
            message_text=text,
            bot_role=await self._manager.identity.bot_role(gateway, group_id),
            sender_role=sender_role,
            mode="admin_command",
        )
        decision = await self._manager.decision_agent.execute(text, context=turn)
        reply = await self._reply_for(turn, decision)
        return decision.action_taken or bool(reply), reply

    async def _reply_for(
        self, turn: TurnContext, decision: DecisionOutcome
    ) -> str | None:
        if not decision.should_reply and not decision.action_taken:
            return None
        return await self._manager.reply_agent.execute(
            ReplySpec(
                manager=self._manager,
                group_id=turn.group_id,
                bot_role=turn.bot_role,
                scenario=decision.scenario,
                actor_id=turn.member_id,
                actor_role=turn.sender_role,
                target_id=decision.target_member_id or turn.member_id,
                executed_actions=list(decision.executed_actions),
                facts={
                    "summary": decision.summary,
                    "tool_outputs": list(turn.tool_outputs),
                    "jev": turn.jev_summary,
                },
                fallback="; ".join(turn.tool_outputs) or decision.summary,
            )
        )

    async def _enforce_without_agent(
        self,
        gateway: Gateway,
        *,
        group_id: str,
        member_id: str,
        message_id: str,
        bot_role: str,
        report: SafetyReport,
    ) -> tuple[bool, str | None]:
        cfg = self.config(group_id)
        reason = f"{report.primary_category} (severity={report.severity})"
        if report.severity <= 1 or report.max_risk < cfg.enforce_confidence:
            outcome = await self.warn(
                gateway,
                group_id,
                member_id,
                category=report.warning_category,
                reason=reason,
            )
        else:
            await self.recall(
                gateway, group_id, message_id, target_id=member_id, reason=reason
            )
            if report.severity == 2:
                outcome = await self.mute(
                    gateway, group_id, member_id, duration=600, reason=reason
                )
            else:
                outcome = await self.kick(
                    gateway,
                    group_id,
                    member_id,
                    reason=reason,
                    blacklist=report.severity >= 4,
                )
        if not outcome.succeeded:
            return False, None
        reply = await self._manager.reply_agent.execute(
            ReplySpec(
                manager=self._manager,
                group_id=group_id,
                bot_role=bot_role,
                scenario="auto_moderation",
                actor_id="bot",
                actor_role=bot_role,
                target_id=member_id,
                executed_actions=[outcome.action],
                facts={"violation": report.primary_category, "detail": outcome.message},
                fallback=outcome.message,
            )
        )
        return True, reply

    # ---- Official QQ v2 actions ----
    async def warn(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        category: WarningCategory = "spam",
        reason: str = "rule violation",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        verdict = await self._manager.safeguard.check_action(
            gateway, group_id, member_id, "warn"
        )
        if not verdict.allowed:
            return self._blocked("warn", group_id, member_id, operator_id, verdict)

        count, threshold = self._manager.warning.record_warning(
            group_id, member_id, category
        )
        hint = (
            self._notice("warn_threshold_hint", current=count, threshold=threshold)
            if count >= threshold
            else ""
        )
        self._audit(group_id, "warn", member_id, operator_id, f"[{category}] {reason}")
        return ActionOutcome(
            succeeded=True,
            action="warn",
            message=self._notice(
                "warn_done",
                member_id=member_id,
                category=category,
                reason=reason,
                extra=hint,
            ),
        )

    async def mute(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        duration: int | str = 600,
        reason: str = "rule violation",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        parsed = parse_duration(duration)
        if parsed is None:
            return ActionOutcome(
                succeeded=False,
                action="mute",
                message=self._notice("invalid_duration", raw=duration),
            )
        verdict = await self._manager.safeguard.check_action(
            gateway, group_id, member_id, "mute", mute_seconds=parsed.seconds
        )
        if not verdict.allowed:
            return self._blocked("mute", group_id, member_id, operator_id, verdict)

        seconds = verdict.effective_mute_seconds or parsed.seconds
        mute_state = SetMemberMuteState(
            member_openid=member_id, op="add", mute_expire_at=timedelta(seconds=seconds)
        )
        try:
            await gateway.set_group_members_mute(group_id, [mute_state])
        except Exception as exc:
            return self._failed("mute", group_id, member_id, operator_id, exc)

        self._manager.safeguard.record_mute(group_id, member_id)
        self._manager.safeguard.increment_daily(group_id, "mute")
        label = format_duration(seconds)
        self._audit(group_id, "mute", member_id, operator_id, f"{label}: {reason}")
        return ActionOutcome(
            succeeded=True,
            action="mute",
            message=self._notice(
                "mute_done", member_id=member_id, duration=label, reason=reason
            ),
        )

    async def unmute(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        if not await self._bot_is_admin(gateway, group_id):
            return self._bot_not_admin("unmute")
        try:
            await gateway.set_group_members_mute(
                group_id, [SetMemberMuteState(member_openid=member_id, op="del")]
            )
        except Exception as exc:
            return self._failed("unmute", group_id, member_id, operator_id, exc)
        self._audit(group_id, "unmute", member_id, operator_id, "unmute")
        return ActionOutcome(
            succeeded=True,
            action="unmute",
            message=self._notice("unmute_done", member_id=member_id),
        )

    async def kick(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        reason: str = "rule violation",
        blacklist: bool = False,
        operator_id: str = "bot",
        require_confirm: bool = False,
    ) -> ActionOutcome:
        verdict = await self._manager.safeguard.check_action(
            gateway, group_id, member_id, "kick", require_confirm=require_confirm
        )
        if not verdict.allowed:
            return self._blocked("kick", group_id, member_id, operator_id, verdict)
        try:
            await gateway.batch_remove_group_members(
                group_id, [member_id], add_to_member_blacklist=blacklist
            )
        except Exception as exc:
            return self._failed("kick", group_id, member_id, operator_id, exc)

        self._manager.safeguard.increment_daily(group_id, "kick")
        self._audit(group_id, "kick", member_id, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action="kick",
            message=self._notice(
                "kick_done",
                member_id=member_id,
                blacklist=str(blacklist).lower(),
                reason=reason,
            ),
        )

    async def ban(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        reason: str = "rule violation",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        verdict = await self._manager.safeguard.check_action(
            gateway, group_id, member_id, "ban"
        )
        if not verdict.allowed:
            return self._blocked("ban", group_id, member_id, operator_id, verdict)
        return await self._update_blacklist(
            gateway,
            group_id,
            member_id,
            op="add",
            reason=reason,
            operator_id=operator_id,
        )

    async def unban(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        if not await self._bot_is_admin(gateway, group_id):
            return self._bot_not_admin("unban")
        return await self._update_blacklist(
            gateway,
            group_id,
            member_id,
            op="del",
            reason="unban",
            operator_id=operator_id,
        )

    async def recall(
        self,
        gateway: Gateway,
        group_id: str,
        message_id: str,
        *,
        target_id: str = "",
        reason: str = "rule violation",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        target = target_id or message_id
        if not await self._bot_is_admin(gateway, group_id):
            return self._bot_not_admin("recall")
        try:
            await gateway.delete_group_message(group_id, message_id)
        except Exception as exc:
            return self._failed("recall", group_id, target, operator_id, exc)
        self._audit(group_id, "recall", target, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action="recall",
            message=self._notice("recall_done", message_id=message_id),
        )

    async def undo(
        self, gateway: Gateway, group_id: str, member_id: str, *, operator_id: str
    ) -> ActionOutcome:
        self._manager.warning.clear_member(group_id, member_id)
        return await self.unmute(gateway, group_id, member_id, operator_id=operator_id)

    async def _update_blacklist(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        op: Literal["add", "del"],
        reason: str,
        operator_id: str,
    ) -> ActionOutcome:
        action = "ban" if op == "add" else "unban"
        try:
            result = await gateway.post_group_member_blacklist(
                group_id, op=op, member_openids=[member_id]
            )
        except Exception as exc:
            return self._failed(action, group_id, member_id, operator_id, exc)
        if member_id in result.fail_openids:
            return self._failed(
                action, group_id, member_id, operator_id, "platform rejected openid"
            )
        if op == "add":
            self._manager.safeguard.increment_daily(group_id, "kick")
        self._audit(group_id, action, member_id, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action=action,
            message=self._notice(f"{action}_done", member_id=member_id),
        )

    async def _bot_is_admin(self, gateway: Gateway, group_id: str) -> bool:
        role = await self._manager.identity.bot_role(gateway, group_id)
        return role in {"owner", "admin"}

    def _notice(self, key: str, **values: object) -> str:
        return self._manager.catalog.format_fallback(key, **values)

    def _bot_not_admin(self, action: str) -> ActionOutcome:
        return ActionOutcome(
            succeeded=False,
            action=action,
            blocked_by="bot_not_admin",
            message=self._notice("bot_not_admin"),
        )

    def _blocked(
        self, action: str, group_id: str, target_id: str, operator_id: str, verdict
    ) -> ActionOutcome:
        self._audit(group_id, action, target_id, operator_id, verdict.reason, False)
        return ActionOutcome(
            succeeded=False,
            action=action,
            blocked_by=verdict.blocked_by,
            message=self._notice("action_blocked", reason=verdict.reason),
        )

    def _failed(
        self,
        action: str,
        group_id: str,
        target_id: str,
        operator_id: str,
        error: object,
    ) -> ActionOutcome:
        self._audit(group_id, action, target_id, operator_id, str(error), False)
        return ActionOutcome(
            succeeded=False,
            action=action,
            message=self._notice("action_failed", reason=error),
        )

    def _audit(
        self,
        group_id: str,
        action: str,
        target_id: str,
        operator_id: str,
        reason: str,
        succeeded: bool = True,
    ) -> None:
        self._manager.audit.record(
            AuditRecord(
                group_id=group_id,
                action=action,
                target_id=target_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=succeeded,
            )
        )


__all__ = [
    "ActionOutcome",
    "ModerationConfig",
    "ModerationModule",
    "WarningCategory",
]
