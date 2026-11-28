"""Automatic moderation: 3-channel Jev routing, dual agents, and QQ v2 actions."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from qq import Gateway, SetMemberMuteState

from qq_admin.manager import MANAGER
from qq_admin.models import (
    ATTACK_FIELDS,
    CRITICAL_FIELDS,
    ORDER_FIELDS,
    SAFETY_FIELDS,
    DecisionOutcome,
    ReplySpec,
    SafetyReport,
    TurnContext,
)
from qq_admin.prompts import notice
from qq_admin.store import CONFIG_STORE, ConfigStore, parse_field_value

from .audit import AUDIT, AuditRecord
from .duration import format_duration, parse_duration
from .identity import IDENTITY
from .safeguard import SAFEGUARD
from .warning import WARNING

WarningCategory = Literal["spam", "abuse", "ad"]
RouteKind = Literal["allow", "attack", "critical_fast", "agent_review"]


class ModerationConfig(BaseModel):
    """Per-group safety toggles, trusted domains, and 3-channel thresholds."""

    enabled: bool = True
    stop_on_violation: bool = True
    allow_admin_nl_control: bool = True
    welcome_new_members: bool = False
    enable_image_review: bool = True
    enable_action_guardrail: bool = False
    max_images: int = Field(default=4, ge=1, le=8)
    disabled_categories: list[str] = Field(default_factory=list)
    trusted_domains: list[str] = Field(
        default_factory=lambda: ["github.com", "bilibili.com", "docs.python.org"]
    )
    critical_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    attack_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    order_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
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
    """Moderates group messages via 3-channel Jev routing and ReplyAgent replies."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

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

    def active_categories(self, group_id: str) -> list[str]:
        disabled = set(self.config(group_id).disabled_categories)
        return [name for name in SAFETY_FIELDS if name not in disabled]

    def filter_urls(self, group_id: str, urls: list[str] | None) -> list[str]:
        if not urls:
            return []
        trusted = tuple(d.lower() for d in self.config(group_id).trusted_domains)
        filtered: list[str] = []
        for url in urls:
            host = (urlparse(url).hostname or "").lower()
            if host and any(host == d or host.endswith(f".{d}") for d in trusted):
                continue
            filtered.append(url)
        return filtered

    def classify_route(
        self, group_id: str, report: SafetyReport
    ) -> tuple[RouteKind, list[str]]:
        """Route a SafetyReport into allow, attack, critical_fast, or agent_review."""
        cfg = self.config(group_id)
        disabled = set(cfg.disabled_categories)

        attack_fields = [f for f in ATTACK_FIELDS if f not in disabled]
        attack_hits = report.triggered(cfg.attack_threshold, attack_fields)
        if attack_hits:
            return "attack", attack_hits

        critical_fields = [f for f in CRITICAL_FIELDS if f not in disabled]
        critical_hits = report.triggered(cfg.critical_threshold, critical_fields)
        if critical_hits:
            if (
                report.severity >= 3
                or max(report.scores(critical_hits).values()) >= 0.80
            ):
                return "critical_fast", critical_hits
            return "agent_review", critical_hits

        order_fields = [f for f in ORDER_FIELDS if f not in disabled]
        order_hits = report.triggered(cfg.order_threshold, order_fields)
        if order_hits and report.severity > 0:
            return "agent_review", order_hits

        return "allow", []

    async def assess(
        self,
        group_id: str,
        *,
        text: str = "",
        images: list[bytes] | None = None,
        urls: list[str] | None = None,
    ) -> SafetyReport:
        """Run stateless Jev.execute() on enabled safety categories."""
        cfg = self.config(group_id)
        selected_images = (
            (images or [])[: cfg.max_images] if cfg.enable_image_review else None
        )
        categories = self.active_categories(group_id)
        try:
            return await MANAGER.jev.execute(
                text=text,
                images=selected_images,
                urls=self.filter_urls(group_id, urls),
                categories=categories,
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
        """3-channel moderation: drop attacks, fast-path critical, review order hits."""
        cfg = self.config(group_id)
        if not cfg.enabled:
            return False, None

        report = await self.assess(group_id, text=text, images=images, urls=urls)
        route, hits = self.classify_route(group_id, report)
        if route == "allow":
            return False, None

        if route == "attack":
            self._audit(
                group_id,
                "attack_blocked",
                member_id,
                "jev",
                f"blocked {hits} (risk={report.max_attack_risk:.2f})",
            )
            return False, None

        bot_role = await IDENTITY.bot_role(gateway, group_id)
        if route == "critical_fast" or not MANAGER.decision_agent.is_ready:
            return await self._enforce_and_compose(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=message_id,
                bot_role=bot_role,
                report=report,
                categories=hits,
                fast_critical=(route == "critical_fast"),
            )

        turn = TurnContext(
            gateway=gateway,
            group_id=group_id,
            member_id=member_id,
            mode="auto_moderate",
            report=report,
        )
        prompt = (
            f"message_id={message_id}\nmember_id={member_id} (role={sender_role})\n"
            f"content={text}\nimages={len(images or [])}\nurls={urls or []}\n"
            f"jev={report.summary(cfg.order_threshold)}"
        )
        decision = await MANAGER.decision_agent.execute(
            prompt, context=turn, bot_role=bot_role, sender_role=sender_role
        )
        return decision.action_taken, await self._reply_for(
            turn,
            decision,
            bot_role=bot_role,
            sender_role=sender_role,
            categories=hits,
        )

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
        del message_id
        cfg = self.config(group_id)
        if not cfg.allow_admin_nl_control or not MANAGER.decision_agent.is_ready:
            return False, None
        bot_role = await IDENTITY.bot_role(gateway, group_id)
        turn = TurnContext(
            gateway=gateway,
            group_id=group_id,
            member_id=member_id,
            mode="admin_command",
        )
        decision = await MANAGER.decision_agent.execute(
            text, context=turn, bot_role=bot_role, sender_role=sender_role
        )
        reply = await self._reply_for(
            turn, decision, bot_role=bot_role, sender_role=sender_role
        )
        return decision.action_taken or bool(reply), reply

    async def _reply_for(
        self,
        turn: TurnContext,
        decision: DecisionOutcome,
        *,
        bot_role: str,
        sender_role: str,
        categories: list[str] | None = None,
    ) -> str | None:
        if not decision.should_reply and not decision.action_taken:
            return None
        return await MANAGER.reply_agent.execute(
            ReplySpec(
                group_id=turn.group_id,
                bot_role=bot_role,
                scenario=decision.scenario,
                actor_id=turn.member_id,
                actor_role=sender_role,
                target_id=decision.target_member_id or turn.member_id,
                categories=list(categories or []),
                executed_actions=list(decision.executed_actions),
                facts={
                    "summary": decision.summary,
                    "tool_outputs": list(turn.tool_outputs),
                    "jev": turn.report.summary() if turn.report else "none",
                },
                fallback="; ".join(turn.tool_outputs) or decision.summary,
            )
        )

    async def _enforce_and_compose(
        self,
        gateway: Gateway,
        *,
        group_id: str,
        member_id: str,
        message_id: str,
        bot_role: str,
        report: SafetyReport,
        categories: list[str],
        fast_critical: bool,
    ) -> tuple[bool, str | None]:
        """Execute moderation actions and delegate reply wording to ReplyAgent."""
        cfg = self.config(group_id)
        label = ", ".join(categories) or report.primary_category
        reason = f"{label} (severity={report.severity})"
        executed: list[str] = []

        if not fast_critical and (
            report.severity <= 1 or report.max_risk < cfg.enforce_confidence
        ):
            outcome = await self.warn(
                gateway,
                group_id,
                member_id,
                category=report.warning_category,
                reason=reason,
            )
        else:
            rec = await self.recall(
                gateway, group_id, message_id, target_id=member_id, reason=reason
            )
            if rec.succeeded:
                executed.append("recall")
            if report.severity <= 2 and not fast_critical:
                outcome = await self.mute(
                    gateway, group_id, member_id, duration=600, reason=reason
                )
            elif report.severity == 3:
                outcome = await self.mute(
                    gateway, group_id, member_id, duration=3600, reason=reason
                )
            else:
                outcome = await self.kick(
                    gateway, group_id, member_id, reason=reason, blacklist=True
                )

        if outcome.succeeded:
            executed.append(outcome.action)
        if not executed:
            return False, None

        reply = await MANAGER.reply_agent.execute(
            ReplySpec(
                group_id=group_id,
                bot_role=bot_role,
                scenario="critical_moderation" if fast_critical else "auto_moderation",
                actor_id="bot",
                actor_role=bot_role,
                target_id=member_id,
                categories=categories,
                executed_actions=executed,
                facts={
                    "categories": categories,
                    "severity": report.severity,
                    "detail": outcome.message,
                },
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
        verdict = await SAFEGUARD.check_action(gateway, group_id, member_id, "warn")
        if not verdict.allowed:
            return self._blocked("warn", group_id, member_id, operator_id, verdict)

        count, threshold = WARNING.record_warning(group_id, member_id, category)
        hint = (
            notice("warn_threshold_hint", current=count, threshold=threshold)
            if count >= threshold
            else ""
        )
        self._audit(group_id, "warn", member_id, operator_id, f"[{category}] {reason}")
        return ActionOutcome(
            succeeded=True,
            action="warn",
            message=notice(
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
                message=notice("invalid_duration", raw=duration),
            )
        verdict = await SAFEGUARD.check_action(
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

        SAFEGUARD.record_mute(group_id, member_id)
        SAFEGUARD.increment_daily(group_id, "mute")
        label = format_duration(seconds)
        self._audit(group_id, "mute", member_id, operator_id, f"{label}: {reason}")
        return ActionOutcome(
            succeeded=True,
            action="mute",
            message=notice(
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
            message=notice("unmute_done", member_id=member_id),
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
        verdict = await SAFEGUARD.check_action(
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

        SAFEGUARD.increment_daily(group_id, "kick")
        self._audit(group_id, "kick", member_id, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action="kick",
            message=notice(
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
        verdict = await SAFEGUARD.check_action(gateway, group_id, member_id, "ban")
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
            message=notice("recall_done", message_id=message_id),
        )

    async def undo(
        self, gateway: Gateway, group_id: str, member_id: str, *, operator_id: str
    ) -> ActionOutcome:
        WARNING.clear_member(group_id, member_id)
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
            SAFEGUARD.increment_daily(group_id, "kick")
        self._audit(group_id, action, member_id, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action=action,
            message=notice(f"{action}_done", member_id=member_id),
        )

    async def _bot_is_admin(self, gateway: Gateway, group_id: str) -> bool:
        return await IDENTITY.bot_role(gateway, group_id) in {"owner", "admin"}

    def _bot_not_admin(self, action: str) -> ActionOutcome:
        return ActionOutcome(
            succeeded=False,
            action=action,
            blocked_by="bot_not_admin",
            message=notice("bot_not_admin"),
        )

    def _blocked(
        self, action: str, group_id: str, target_id: str, operator_id: str, verdict
    ) -> ActionOutcome:
        self._audit(group_id, action, target_id, operator_id, verdict.reason, False)
        return ActionOutcome(
            succeeded=False,
            action=action,
            blocked_by=verdict.blocked_by,
            message=notice("action_blocked", reason=verdict.reason),
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
            message=notice("action_failed", reason=error),
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
        AUDIT.record(
            AuditRecord(
                group_id=group_id,
                action=action,
                target_id=target_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=succeeded,
            )
        )


MODERATION = ModerationModule(CONFIG_STORE)

__all__ = [
    "MODERATION",
    "ActionOutcome",
    "ModerationConfig",
    "ModerationModule",
    "RouteKind",
    "WarningCategory",
]
