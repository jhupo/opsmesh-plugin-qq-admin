"""Pydantic v2 configuration models and external TOML prompt resource loader."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_PROMPTS_FILE = Path(__file__).parent / "resources" / "prompts.toml"


class AdminConfig(BaseModel):
    """Operator permission settings for commands and natural-language control."""

    admins: list[str] = Field(default_factory=list)
    allow_group_owner: bool = True
    owner_allowed_commands: list[str] = Field(default_factory=list)
    deny_response: Literal["silent", "reply"] = "silent"


class AutoModerateConfig(BaseModel):
    """Automatic moderation scope, role cache TTLs, and propagation control."""

    enabled: bool = True
    enabled_groups: list[str] = Field(default_factory=list)
    stop_on_violation: bool = True
    allow_admin_nl_control: bool = True
    role_cache_ttl_seconds: int = Field(default=600, ge=30)
    bot_role_refresh_seconds: int = Field(default=300, ge=30)
    sender_role_refresh_seconds: int = Field(default=120, ge=15)
    recent_context_size: int = Field(default=20, ge=5, le=100)


class JevConfig(BaseModel):
    """System 1 TypeSafe AI Jev client and calibrated decision thresholds."""

    enabled: bool = True
    api_key: str = ""
    model: str = "jev-1"
    proxy: str = ""
    timeout_seconds: float = Field(default=10.0, gt=0)
    injection_block_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    warn_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    auto_enforce_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    action_validity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    output_safety_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    join_reject_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    enable_image_review: bool = True
    enable_action_guardrail: bool = True
    max_images: int = Field(default=4, ge=1, le=8)


class LLMConfig(BaseModel):
    """System 2 dual OpenAI Agents SDK settings (decision agent + reply agent)."""

    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    decision_model: str = "gpt-5-mini"
    reply_model: str = ""
    reply_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    reply_persona: str = ""
    use_chat_completions: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_turns: int = Field(default=6, ge=1, le=16)

    @property
    def effective_reply_model(self) -> str:
        return self.reply_model.strip() or self.decision_model


class SafeguardConfig(BaseModel):
    """Role-aware hard safety limits applied when the bot is a group admin."""

    max_mute_duration: int = Field(default=3600, ge=60, le=2_592_000)
    mute_cooldown: int = Field(default=300, ge=0)
    daily_mute_limit: int = Field(default=10, ge=1)
    daily_kick_limit: int = Field(default=3, ge=1)
    protected_users: list[str] = Field(default_factory=list)
    exempt_users: dict[str, list[str]] = Field(default_factory=dict)
    auto_exempt_admins: bool = True
    kick_require_member_check: bool = True


class WarningConfig(BaseModel):
    """Sliding-window warning counter thresholds per violation category."""

    enabled: bool = True
    spam_threshold: int = Field(default=3, ge=1)
    spam_window_seconds: int = Field(default=600, ge=60)
    abuse_threshold: int = Field(default=1, ge=1)
    abuse_window_seconds: int = Field(default=3600, ge=60)
    ad_threshold: int = Field(default=1, ge=1)
    ad_window_seconds: int = Field(default=1800, ge=60)


class EscalationStep(BaseModel):
    """Single punishment escalation rule within a lookback window."""

    within_hours: float = Field(default=24.0, gt=0)
    count: int = Field(default=1, ge=1)
    action: Literal["mute", "kick"] = "mute"
    mute_seconds: int = Field(default=600, ge=60, le=2_592_000)
    add_to_blacklist: bool = False


class EscalationConfig(BaseModel):
    """Progressive punishment ladder based on recent moderation actions."""

    enabled: bool = True
    steps: list[EscalationStep] = Field(
        default_factory=lambda: [
            EscalationStep(within_hours=24, count=1, action="mute", mute_seconds=600),
            EscalationStep(within_hours=24, count=2, action="mute", mute_seconds=1800),
            EscalationStep(
                within_hours=72,
                count=3,
                action="kick",
                mute_seconds=3600,
                add_to_blacklist=True,
            ),
        ]
    )


class GroupApproveOverride(BaseModel):
    """Per-group override for automatic join request review."""

    group_openid: str = ""
    default_action: Literal["ignore", "approve", "reject"] = "ignore"
    daily_approve_limit: int = Field(default=0, ge=0)
    daily_reject_limit: int = Field(default=0, ge=0)


class AutoApproveConfig(BaseModel):
    """Automatic join request review powered by platform risk_tips + Jev."""

    enabled: bool = False
    default_action: Literal["ignore", "approve", "reject"] = "ignore"
    reject_on_risk_tips: bool = True
    use_jev_review: bool = True
    max_pending_seconds: int = Field(default=300, ge=30)
    daily_approve_limit: int = Field(default=10, ge=1)
    daily_reject_limit: int = Field(default=20, ge=1)
    check_interval_seconds: int = Field(default=120, ge=0)
    groups: list[GroupApproveOverride] = Field(default_factory=list)


class LoggingConfig(BaseModel):
    """In-memory operation audit log retention settings."""

    max_log_entries: int = Field(default=2000, ge=100)
    default_log_lines: int = Field(default=10, ge=1, le=100)


class QQAdminConfig(BaseModel):
    """Top-level configuration for opsmesh-plugin-qq-admin."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    prompts_path: str = ""
    admin: AdminConfig = Field(default_factory=AdminConfig)
    auto_moderate: AutoModerateConfig = Field(default_factory=AutoModerateConfig)
    jev: JevConfig = Field(default_factory=JevConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    safeguard: SafeguardConfig = Field(default_factory=SafeguardConfig)
    warning: WarningConfig = Field(default_factory=WarningConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    auto_approve: AutoApproveConfig = Field(default_factory=AutoApproveConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class _OpsMeshPluginConfigWrapper(BaseModel):
    """Allows reading nested QQ_ADMIN__* env vars via opsmesh.get_plugin_config."""

    model_config = ConfigDict(extra="ignore")

    qq_admin: QQAdminConfig = Field(default_factory=QQAdminConfig)


@lru_cache(maxsize=4)
def _load_toml_cached(resolved_path: str) -> dict[str, Any]:
    with Path(resolved_path).open("rb") as fp:
        return tomllib.load(fp)


def load_prompts(prompts_path: str | Path = "") -> dict[str, Any]:
    """Load localized prompt templates and Jev criteria from external TOML."""
    target = Path(prompts_path) if str(prompts_path).strip() else _DEFAULT_PROMPTS_FILE
    return _load_toml_cached(str(target.resolve()))


def render_fallback_message(prompts: dict[str, Any], key: str, **kwargs: Any) -> str:
    """Format a deterministic fallback template when reply LLM is disabled."""
    template = str(prompts.get("fallback_messages", {}).get(key, key))
    return template.format(**kwargs) if kwargs else template


__all__ = [
    "AdminConfig",
    "AutoApproveConfig",
    "AutoModerateConfig",
    "EscalationConfig",
    "EscalationStep",
    "GroupApproveOverride",
    "JevConfig",
    "LLMConfig",
    "LoggingConfig",
    "QQAdminConfig",
    "SafeguardConfig",
    "WarningConfig",
    "_OpsMeshPluginConfigWrapper",
    "load_prompts",
    "render_fallback_message",
]
