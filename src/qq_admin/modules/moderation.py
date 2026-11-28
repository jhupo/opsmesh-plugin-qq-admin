"""Deterministic moderation planner: flood/Jev checks, QQ v2 actions, and ReplyAgent."""

from dataclasses import dataclass
from datetime import timedelta
import re
import time
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from qq import Gateway, SetMemberMuteState

from qq_admin.exception import ConfigError
from qq_admin.manager import MANAGER
from qq_admin.models import (
    ATTACK_FIELDS,
    CRITICAL_FIELDS,
    ORDER_FIELDS,
    SAFETY_FIELDS,
    ReplySpec,
    SafetyReport,
)
from qq_admin.prompts import notice
from qq_admin.store import CONFIG_STORE, ConfigStore, parse_field_value

from .audit import AUDIT, AuditRecord
from .duration import format_duration, parse_duration
from .identity import IDENTITY
from .safeguard import SAFEGUARD
from .warning import WARNING

WarningCategory = Literal["spam", "abuse", "ad"]
RouteKind = Literal["allow", "attack", "order", "critical"]

_URL_CLEAN_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class ModerationConfig(BaseModel):
    """Per-group safety toggles, flood limits, trusted domains, and Jev thresholds."""

    enabled: bool = True
    stop_on_violation: bool = True
    welcome_new_members: bool = False
    enable_image_review: bool = True
    max_images: int = Field(default=4, ge=1, le=8)
    default_mute_seconds: int = Field(default=600, ge=60, le=2_592_000)
    auto_mute_on_warn_threshold: bool = True
    flood_enabled: bool = True
    flood_window_seconds: int = Field(default=10, ge=3, le=300)
    flood_max_messages: int = Field(default=6, ge=2, le=50)
    repeat_max_messages: int = Field(default=3, ge=2, le=20)
    group_rule_hint: str = ""
    disabled_categories: list[str] = Field(default_factory=list)
    trusted_domains: list[str] = Field(
        default_factory=lambda: ["github.com", "bilibili.com", "docs.python.org"]
    )
    critical_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    attack_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    order_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    enforce_confidence: float = Field(default=0.82, ge=0.0, le=1.0)


@dataclass(slots=True)
class ActionOutcome:
    """Outcome of one moderation action."""

    succeeded: bool
    action: str
    message: str
    blocked_by: str = ""


class ModerationModule:
    """Fixed moderation pipeline + target-authorized Official QQ v2 management API."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._flood_tracker: dict[tuple[str, str], list[tuple[float, str]]] = {}

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
            "moderation",
            validated.model_dump(),
            group_id=group_id,
            defaults=ModerationConfig().model_dump(),
        )
        return validated

    def reset_config(self, group_id: str, key: str | None = None) -> ModerationConfig:
        if key and key not in ModerationConfig.model_fields:
            raise ConfigError(f"Unknown config field: {key}")
        self._store.reset_section("moderation", key, group_id=group_id)
        return self.config(group_id)

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

    def check_flood(
        self, group_id: str, member_id: str, text: str
    ) -> Literal["flood", "repeat"] | None:
        """Pure-code sliding-window flood and duplicate-message rate limiter."""
        cfg = self.config(group_id)
        if not cfg.flood_enabled:
            return None
        now = time.monotonic()
        normalized = " ".join(text.split()).lower()
        key = (group_id, member_id)
        recent = [
            (ts, body)
            for ts, body in self._flood_tracker.get(key, [])
            if now - ts <= cfg.flood_window_seconds
        ]
        recent.append((now, normalized))
        self._flood_tracker[key] = recent

        if len(recent) >= cfg.flood_max_messages:
            return "flood"
        if normalized and (
            sum(1 for _, body in recent if body == normalized)
            >= cfg.repeat_max_messages
        ):
            return "repeat"
        return None

    def classify_route(
        self, group_id: str, report: SafetyReport
    ) -> tuple[RouteKind, list[str]]:
        """Route a SafetyReport into allow, attack, order, or critical."""
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
                return "critical", critical_hits
            return "order", critical_hits

        order_fields = [f for f in ORDER_FIELDS if f not in disabled]
        order_hits = report.triggered(cfg.order_threshold, order_fields)
        if order_hits and report.severity > 0:
            return "order", order_hits

        return "allow", []

    async def assess(
        self,
        group_id: str,
        *,
        text: str = "",
        images: list[bytes] | None = None,
        urls: list[str] | None = None,
    ) -> SafetyReport:
        """Run stateless Jev.execute() when non-empty untrusted content is present."""
        cfg = self.config(group_id)
        selected_images = (
            (images or [])[: cfg.max_images] if cfg.enable_image_review else None
        )
        untrusted_urls = self.filter_urls(group_id, urls)
        stripped_text = _URL_CLEAN_RE.sub("", text).strip() if urls else text.strip()
        if not stripped_text and not untrusted_urls and not selected_images:
            return SafetyReport()

        categories = self.active_categories(group_id)
        try:
            return await MANAGER.jev.execute(
                text=text if (stripped_text or untrusted_urls) else "",
                images=selected_images,
                urls=untrusted_urls,
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
        sender_role: str = "member",
        images: list[bytes] | None = None,
        urls: list[str] | None = None,
    ) -> tuple[bool, str | None]:
        """Fixed pipeline: flood check -> Jev -> deterministic action -> ReplyAgent."""
        del sender_role
        cfg = self.config(group_id)
        if not cfg.enabled or SAFEGUARD.is_whitelisted(group_id, member_id):
            return False, None

        if flood_kind := self.check_flood(group_id, member_id, text):
            bot_role = await IDENTITY.bot_role(gateway, group_id)
            return await self._enforce_and_compose(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=message_id,
                bot_role=bot_role,
                severity=2,
                max_risk=1.0,
                warning_category="spam",
                categories=[flood_kind],
                critical=False,
                reason_override=notice("flood_reason"),
            )

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
            return True, None

        bot_role = await IDENTITY.bot_role(gateway, group_id)
        return await self._enforce_and_compose(
            gateway,
            group_id=group_id,
            member_id=member_id,
            message_id=message_id,
            bot_role=bot_role,
            severity=report.severity,
            max_risk=report.max_risk,
            warning_category=report.warning_category,
            categories=hits,
            critical=(route == "critical"),
        )

    async def _enforce_and_compose(
        self,
        gateway: Gateway,
        *,
        group_id: str,
        member_id: str,
        message_id: str,
        bot_role: str,
        severity: int,
        max_risk: float,
        warning_category: WarningCategory,
        categories: list[str],
        critical: bool,
        reason_override: str = "",
    ) -> tuple[bool, str | None]:
        """Deterministically execute moderation actions and compose persona reply."""
        cfg = self.config(group_id)
        label = ", ".join(categories) or warning_category
        reason = reason_override or f"{label} (severity={severity})"
        executed: list[str] = []

        if not critical and (severity <= 1 or max_risk < cfg.enforce_confidence):
            outcome = await self.warn(
                gateway,
                group_id,
                member_id,
                category=warning_category,
                reason=reason,
            )
        else:
            rec = await self.recall(
                gateway, group_id, message_id, target_id=member_id, reason=reason
            )
            if rec.succeeded:
                executed.append("recall")
            if severity <= 2 and not critical:
                outcome = await self.mute(
                    gateway,
                    group_id,
                    member_id,
                    duration=cfg.default_mute_seconds,
                    reason=reason,
                )
            elif severity == 3:
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
                scenario="critical_moderation" if critical else "auto_moderation",
                actor_id="bot",
                actor_role=bot_role,
                target_id=member_id,
                categories=categories,
                executed_actions=executed,
                facts={
                    "categories": categories,
                    "severity": severity,
                    "detail": outcome.message,
                },
                fallback=outcome.message,
            )
        )
        return True, reply

    # ---- Official QQ v2 actions (safe for slash commands & external plugins) ----
    async def _authorize_operator(
        self,
        gateway: Gateway,
        group_id: str,
        action: str,
        target_id: str,
        operator_id: str,
    ) -> ActionOutcome | None:
        if operator_id == "bot":
            return None
        if await IDENTITY.is_admin(gateway, group_id, operator_id):
            return None
        self._audit(
            group_id, action, target_id, operator_id, "operator not admin", False
        )
        return ActionOutcome(
            succeeded=False,
            action=action,
            blocked_by="permission_denied",
            message=notice("denied"),
        )

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
        if denied := await self._authorize_operator(
            gateway, group_id, "warn", member_id, operator_id
        ):
            return denied
        verdict = await SAFEGUARD.check_action(gateway, group_id, member_id, "warn")
        if not verdict.allowed:
            return self._blocked("warn", group_id, member_id, operator_id, verdict)

        count, threshold = WARNING.record_warning(group_id, member_id, category)
        self._audit(group_id, "warn", member_id, operator_id, f"[{category}] {reason}")

        cfg = self.config(group_id)
        if count >= threshold and cfg.auto_mute_on_warn_threshold:
            mute_res = await self.mute(
                gateway,
                group_id,
                member_id,
                duration=cfg.default_mute_seconds,
                reason=f"{category} {count}/{threshold}: {reason}",
                operator_id=operator_id,
            )
            if mute_res.succeeded:
                extra = notice(
                    "warn_escalated_hint",
                    current=count,
                    threshold=threshold,
                    detail=mute_res.message,
                )
                return ActionOutcome(
                    succeeded=True,
                    action=mute_res.action,
                    message=notice(
                        "warn_done",
                        member_id=member_id,
                        category=category,
                        reason=reason,
                        extra=extra,
                    ),
                )

        hint = (
            notice("warn_threshold_hint", current=count, threshold=threshold)
            if count >= threshold
            else ""
        )
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
        if denied := await self._authorize_operator(
            gateway, group_id, "mute", member_id, operator_id
        ):
            return denied
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

        if verdict.escalated_action == "kick":
            blacklist = bool(
                verdict.escalation_rule and verdict.escalation_rule.blacklist
            )
            return await self.kick(
                gateway,
                group_id,
                member_id,
                reason=reason,
                blacklist=blacklist,
                operator_id=operator_id,
                require_confirm=False,
            )

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
        if denied := await self._authorize_operator(
            gateway, group_id, "unmute", member_id, operator_id
        ):
            return denied
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
        if denied := await self._authorize_operator(
            gateway, group_id, "kick", member_id, operator_id
        ):
            return denied
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
        if denied := await self._authorize_operator(
            gateway, group_id, "ban", member_id, operator_id
        ):
            return denied
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
        if denied := await self._authorize_operator(
            gateway, group_id, "unban", member_id, operator_id
        ):
            return denied
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
        if denied := await self._authorize_operator(
            gateway, group_id, "recall", target, operator_id
        ):
            return denied
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
        if denied := await self._authorize_operator(
            gateway, group_id, "undo", member_id, operator_id
        ):
            return denied
        WARNING.clear_member(group_id, member_id)
        self.clear_member(group_id, member_id)
        return await self.unmute(gateway, group_id, member_id, operator_id=operator_id)

    def clear_member(self, group_id: str, member_id: str) -> None:
        self._flood_tracker.pop((group_id, member_id), None)

    def forget_group(self, group_id: str) -> None:
        for key in [k for k in self._flood_tracker if k[0] == group_id]:
            self._flood_tracker.pop(key, None)

    def clear(self) -> None:
        self._flood_tracker.clear()

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
