"""Automatic moderation module: Jev assessment, dual agents, and QQ v2 actions."""

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from qq import Gateway, SetMemberMuteState
from typesafe_sdk import Choice, Image, Noul, Score

from qq_admin.config import ConfigStore, parse_field_value
from qq_admin.models import DecisionOutcome, ReplySpec, TurnContext

from .audit import AuditRecord
from .duration import format_duration, parse_duration

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager

WarningCategory = Literal["spam", "abuse", "ad"]

_AD_LABELS = {"commercial_ad", "qr_ad_promo", "scam_phishing", "scam_screenshot"}
_ABUSE_LABELS = {"harassment_abuse", "flame_bait", "doxxing_privacy"}


class ModerationConfig(BaseModel):
    """Automatic moderation switches and calibrated Jev thresholds."""

    enabled: bool = True
    stop_on_violation: bool = True
    allow_admin_nl_control: bool = True
    welcome_new_members: bool = False
    recent_context_size: int = Field(default=20, ge=5, le=100)
    enable_image_review: bool = True
    enable_action_guardrail: bool = True
    max_images: int = Field(default=4, ge=1, le=8)
    injection_block_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    banter_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    warn_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    enforce_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    action_validity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    output_safety_threshold: float = Field(default=0.80, ge=0.0, le=1.0)


@dataclass(slots=True)
class MessageSnapshot:
    """Compact message kept in the per-group sliding context buffer."""

    message_id: str
    member_id: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class ActionOutcome:
    """Outcome of one moderation action."""

    succeeded: bool
    action: str
    message: str
    blocked_by: str = ""


@dataclass(slots=True)
class MessageAssessment:
    """Calibrated Jev assessment of one inbound group message."""

    injection_prob: float = 0.0
    text_violation: str = "none"
    text_confidence: float = 0.0
    image_violation: str = "none"
    image_confidence: float = 0.0
    banter_prob: float = 0.0
    severity: int = 0
    severity_confidence: float = 0.0

    @property
    def violation(self) -> str:
        if self.text_violation != "none":
            return self.text_violation
        return self.image_violation

    @property
    def confidence(self) -> float:
        return max(
            self.text_confidence, self.image_confidence, self.severity_confidence
        )

    @property
    def category(self) -> WarningCategory:
        if self.violation in _AD_LABELS:
            return "ad"
        if self.violation in _ABUSE_LABELS:
            return "abuse"
        return "spam"

    def requires_action(self, cfg: ModerationConfig) -> bool:
        if self.injection_prob >= cfg.injection_block_threshold:
            return False
        if self.violation == "none" or self.severity <= 0:
            return False
        if self.banter_prob >= cfg.banter_threshold and self.severity <= 1:
            return False
        return self.confidence >= cfg.warn_confidence

    def summary(self) -> str:
        return (
            f"violation={self.violation}, severity={self.severity}, "
            f"confidence={self.confidence:.2f}, banter={self.banter_prob:.2f}, "
            f"injection={self.injection_prob:.2f}"
        )


class ModerationModule:
    """Moderates group messages and executes Official QQ v2 admin actions."""

    def __init__(self, store: ConfigStore, manager: "ServiceManager") -> None:
        self._store = store
        self._manager = manager
        self._recent: dict[str, deque[MessageSnapshot]] = {}

    # ---- configuration ----
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

    # ---- context buffer ----
    def remember(
        self, group_id: str, message_id: str, member_id: str, content: str
    ) -> None:
        size = self.config(group_id).recent_context_size
        buffer = self._recent.get(group_id)
        if buffer is None or buffer.maxlen != size:
            buffer = deque(buffer or (), maxlen=size)
            self._recent[group_id] = buffer
        buffer.append(MessageSnapshot(message_id, member_id, content))

    def recent_messages(self, group_id: str, limit: int = 10) -> list[MessageSnapshot]:
        buffer = self._recent.get(group_id)
        return list(buffer)[-limit:] if buffer else []

    def forget_group(self, group_id: str) -> None:
        self._recent.pop(group_id, None)

    # ---- Jev assessment ----
    async def assess(
        self,
        group_id: str,
        member_id: str,
        text: str,
        *,
        images: list[bytes] | None = None,
    ) -> MessageAssessment:
        cfg = self.config(group_id)
        jev = self._manager.jev
        if not jev.is_ready:
            return MessageAssessment()

        assets = (
            {
                f"img_{i}": Image(raw)
                for i, raw in enumerate((images or [])[: cfg.max_images], start=1)
            }
            if cfg.enable_image_review
            else {}
        )
        if not text.strip() and not assets:
            return MessageAssessment()

        catalog = self._manager.catalog
        questions: dict[str, Noul | Choice | Score] = {
            "injection": Noul(instructions=catalog.jev_incoming("is_prompt_injection")),
            "text_violation": Choice(
                instructions=catalog.jev_incoming("text_violation_instructions"),
                criteria=catalog.jev_incoming_criteria("text_violation_criteria"),
            ),
            "banter": Noul(instructions=catalog.jev_incoming("is_friendly_banter")),
            "severity": Score(
                instructions=catalog.jev_incoming("violation_severity_instructions"),
                criteria=catalog.jev_incoming_list("violation_severity_criteria"),
            ),
        }
        if assets:
            questions["image_violation"] = Choice(
                instructions=catalog.jev_incoming("image_violation_instructions"),
                criteria=catalog.jev_incoming_criteria("image_violation_criteria"),
            )

        inputs = {
            "group_id": group_id,
            "member_id": member_id,
            "text": text[:2000],
            "recent_messages": [
                {"member_id": m.member_id, "content": m.content[:200]}
                for m in self.recent_messages(group_id)
            ],
            "attached_images": list(assets),
        }
        try:
            resp = await jev.execute(inputs, questions, images=assets)
        except Exception:
            return MessageAssessment()

        text_answer = resp.choices["text_violation"]
        severity = resp.scores["severity"]
        image_answer = resp.choices.get("image_violation") if assets else None
        return MessageAssessment(
            injection_prob=float(resp.nouls["injection"].noul),
            text_violation=str(text_answer.choice),
            text_confidence=float(text_answer.confidence),
            image_violation=str(image_answer.choice) if image_answer else "none",
            image_confidence=float(image_answer.confidence) if image_answer else 0.0,
            banter_prob=float(resp.nouls["banter"].noul),
            severity=round(float(severity.score)),
            severity_confidence=float(severity.confidence),
        )

    # ---- message pipelines ----
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
    ) -> tuple[bool, str | None]:
        """Jev assessment -> DecisionAgent -> ReplyAgent; silent on normal chat."""
        cfg = self.config(group_id)
        if not cfg.enabled:
            return False, None
        assessment = await self.assess(group_id, member_id, text, images=images)
        if not assessment.requires_action(cfg):
            return False, None

        bot_role = await self._manager.identity.bot_role(gateway, group_id)
        if not self._manager.decision_agent.is_ready:
            return await self._enforce_without_agent(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=message_id,
                bot_role=bot_role,
                assessment=assessment,
            )

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
            jev_summary=assessment.summary(),
        )
        prompt = (
            f"message_id={message_id}\nmember_id={member_id} (role={sender_role})\n"
            f"content={text}\nimages={len(images or [])}\njev={assessment.summary()}"
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
        assessment: MessageAssessment,
    ) -> tuple[bool, str | None]:
        cfg = self.config(group_id)
        reason = f"{assessment.violation} (severity={assessment.severity})"
        if assessment.severity <= 1 or assessment.confidence < cfg.enforce_confidence:
            outcome = await self.warn(
                gateway,
                group_id,
                member_id,
                category=assessment.category,
                reason=reason,
            )
        else:
            await self.recall(
                gateway, group_id, message_id, target_id=member_id, reason=reason
            )
            if assessment.severity == 2:
                outcome = await self.mute(
                    gateway, group_id, member_id, duration=600, reason=reason
                )
            else:
                outcome = await self.kick(
                    gateway,
                    group_id,
                    member_id,
                    reason=reason,
                    blacklist=assessment.severity >= 4,
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
                facts={"violation": assessment.violation, "detail": outcome.message},
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

    # ---- helpers ----
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
    "MessageAssessment",
    "MessageSnapshot",
    "ModerationConfig",
    "ModerationModule",
    "WarningCategory",
]
