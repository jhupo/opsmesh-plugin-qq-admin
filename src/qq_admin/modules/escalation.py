"""Progressive punishment escalation module with self-owned EscalationConfig."""

from typing import Literal

from pydantic import BaseModel, Field

from qq_admin.store import ConfigStore, parse_field_value

from .audit import AuditModule


class EscalationRule(BaseModel):
    """Single progressive punishment step within a lookback window."""

    within_hours: float = Field(default=24.0, gt=0)
    count: int = Field(default=1, ge=1)
    action: Literal["mute", "kick"] = "mute"
    mute_seconds: int = Field(default=600, ge=60, le=2_592_000)
    blacklist: bool = False


class EscalationConfig(BaseModel):
    """Progressive punishment ladder based on recent moderation history."""

    enabled: bool = True
    steps: list[EscalationRule] = Field(
        default_factory=lambda: [
            EscalationRule(within_hours=24, count=1, action="mute", mute_seconds=600),
            EscalationRule(within_hours=24, count=2, action="mute", mute_seconds=1800),
            EscalationRule(
                within_hours=72,
                count=3,
                action="kick",
                mute_seconds=3600,
                blacklist=True,
            ),
        ]
    )


class EscalationModule:
    """Computes progressive escalation overrides from recent member history."""

    def __init__(self, store: ConfigStore, audit: AuditModule) -> None:
        self._store = store
        self._audit = audit

    def config(self, group_id: str | None = None) -> EscalationConfig:
        raw = self._store.load_section("escalation", group_id=group_id)
        return EscalationConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> EscalationConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(EscalationConfig, key, raw_value)
        validated = EscalationConfig.model_validate(current)
        self._store.save_section(
            "escalation", validated.model_dump(), group_id=group_id
        )
        return validated

    def resolve_step(self, group_id: str, member_id: str) -> EscalationRule | None:
        cfg = self.config(group_id)
        if not cfg.enabled or not cfg.steps:
            return None
        matched: EscalationRule | None = None
        for step in cfg.steps:
            recent = self._audit.count_member_actions(
                group_id, member_id, within_hours=step.within_hours
            )
            if recent >= step.count:
                matched = step
        return matched


__all__ = ["EscalationConfig", "EscalationModule", "EscalationRule"]
