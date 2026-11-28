"""Symmetric Pydantic v2 configuration sections supporting TOML and OpsMesh env."""

from pathlib import Path
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PluginSettings(BaseModel):
    """Master plugin switch and external prompt file override."""

    enabled: bool = Field(default=True, description="Enable the plugin globally.")
    prompts_path: str = Field(
        default="", description="Optional path to custom prompts.toml."
    )


class AdminSettings(BaseModel):
    """Human administrator authorization rules."""

    admins: list[str] = Field(
        default_factory=list, description="Global admin member_openid allowlist."
    )
    allow_group_owner: bool = Field(
        default=True, description="Allow group owners to run /admin commands."
    )
    owner_allowed_commands: list[str] = Field(
        default_factory=list,
        description="Optional subcommand allowlist for group owners.",
    )
    deny_response: Literal["silent", "reply"] = Field(
        default="silent",
        description="Behavior when an unauthorized user runs a command.",
    )


class IdentitySettings(BaseModel):
    """TTL and refresh intervals for group member and bot role lookups."""

    role_cache_ttl_seconds: int = Field(
        default=600, ge=30, description="Member role cache TTL in seconds."
    )
    bot_role_refresh_seconds: int = Field(
        default=300, ge=30, description="Bot self-role refresh interval in seconds."
    )
    sender_role_refresh_seconds: int = Field(
        default=120, ge=15, description="Active speaker role refresh interval."
    )


class ModerationSettings(BaseModel):
    """Automatic group message moderation scope and propagation behavior."""

    enabled: bool = Field(
        default=True, description="Enable automatic inbound message moderation."
    )
    enabled_groups: list[str] = Field(
        default_factory=list,
        description="Group allowlist; empty means all groups are active.",
    )
    stop_on_violation: bool = Field(
        default=True,
        description="Stop downstream matchers once a violation is handled.",
    )
    allow_admin_nl_control: bool = Field(
        default=True,
        description="Allow owners/admins to control the bot via @mention instructions.",
    )
    recent_context_size: int = Field(
        default=20, ge=5, le=100, description="Per-group sliding context buffer size."
    )


class JevSettings(BaseModel):
    """System 1 TypeSafe AI Jev client and calibrated probability thresholds."""

    enabled: bool = Field(default=True, description="Enable TypeSafe Jev evaluations.")
    api_key: SecretStr = Field(
        default=SecretStr(""), description="TypeSafe API key (or TYPESAFE_API_KEY env)."
    )
    model: str = Field(default="jev-1", description="TypeSafe System One model name.")
    proxy: str = Field(default="", description="Optional HTTP/SOCKS5 proxy URL.")
    timeout_seconds: float = Field(
        default=10.0, gt=0, description="Request timeout in seconds."
    )
    injection_block_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    warn_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    enforce_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    action_validity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    output_safety_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    join_reject_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    enable_image_review: bool = Field(default=True)
    enable_action_guardrail: bool = Field(default=True)
    max_images: int = Field(default=4, ge=1, le=8)

    @property
    def secret_value(self) -> str:
        return self.api_key.get_secret_value().strip()


class AgentSettings(BaseModel):
    """System 2 dual OpenAI Agents SDK settings (DecisionPlanner + ReplyComposer)."""

    enabled: bool = Field(
        default=False, description="Enable OpenAI Agents SDK decision & reply agents."
    )
    api_key: SecretStr = Field(
        default=SecretStr(""), description="OpenAI or compatible endpoint API key."
    )
    base_url: str = Field(default="", description="Optional custom OpenAI base URL.")
    decision_model: str = Field(
        default="gpt-5-mini", description="Model used by DecisionPlanner."
    )
    reply_model: str = Field(
        default="",
        description="Model used by ReplyComposer; defaults to decision_model.",
    )
    reply_temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature for replies."
    )
    reply_persona: str = Field(
        default="", description="Optional custom persona overriding prompts.toml."
    )
    use_chat_completions: bool = Field(default=False)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_turns: int = Field(default=6, ge=1, le=16)

    @property
    def secret_value(self) -> str:
        return self.api_key.get_secret_value().strip()

    @property
    def effective_reply_model(self) -> str:
        return self.reply_model.strip() or self.decision_model


class SafeguardSettings(BaseModel):
    """Role-aware hard safety limits enforced when the bot is a group admin."""

    max_mute_duration: int = Field(default=3600, ge=60, le=2_592_000)
    mute_cooldown: int = Field(default=300, ge=0)
    daily_mute_limit: int = Field(default=10, ge=1)
    daily_kick_limit: int = Field(default=3, ge=1)
    protected_users: list[str] = Field(default_factory=list)
    exempt_users: dict[str, list[str]] = Field(default_factory=dict)
    auto_exempt_admins: bool = True
    kick_require_confirm: bool = True


class WarningSettings(BaseModel):
    """Sliding-window warning thresholds per violation category."""

    enabled: bool = True
    spam_threshold: int = Field(default=3, ge=1)
    spam_window_seconds: int = Field(default=600, ge=60)
    abuse_threshold: int = Field(default=1, ge=1)
    abuse_window_seconds: int = Field(default=3600, ge=60)
    ad_threshold: int = Field(default=1, ge=1)
    ad_window_seconds: int = Field(default=1800, ge=60)


class EscalationRule(BaseModel):
    """Single progressive punishment step within a lookback window."""

    within_hours: float = Field(default=24.0, gt=0)
    count: int = Field(default=1, ge=1)
    action: Literal["mute", "kick"] = "mute"
    mute_seconds: int = Field(default=600, ge=60, le=2_592_000)
    blacklist: bool = False


class EscalationSettings(BaseModel):
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


class GroupApprovalPolicy(BaseModel):
    """Per-group override for automatic join request approval."""

    group_id: str = ""
    default_action: Literal["ignore", "approve", "reject"] = "ignore"
    daily_approve_limit: int = Field(default=0, ge=0)
    daily_reject_limit: int = Field(default=0, ge=0)


class ApprovalSettings(BaseModel):
    """Automatic join-request review powered by platform risk_tips and Jev."""

    enabled: bool = False
    default_action: Literal["ignore", "approve", "reject"] = "ignore"
    reject_on_risk_tips: bool = True
    use_jev_review: bool = True
    max_pending_seconds: int = Field(default=300, ge=30)
    daily_approve_limit: int = Field(default=10, ge=1)
    daily_reject_limit: int = Field(default=20, ge=1)
    check_interval_seconds: int = Field(default=120, ge=0)
    groups: list[GroupApprovalPolicy] = Field(default_factory=list)


class LoggingSettings(BaseModel):
    """In-memory audit log retention settings."""

    max_log_entries: int = Field(default=2000, ge=100)
    default_log_lines: int = Field(default=10, ge=1, le=100)


class AdminConfig(BaseModel):
    """Complete structured configuration for opsmesh-plugin-qq-admin."""

    model_config = ConfigDict(extra="ignore")

    plugin: PluginSettings = Field(default_factory=PluginSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    identity: IdentitySettings = Field(default_factory=IdentitySettings)
    moderation: ModerationSettings = Field(default_factory=ModerationSettings)
    jev: JevSettings = Field(default_factory=JevSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    safeguard: SafeguardSettings = Field(default_factory=SafeguardSettings)
    warning: WarningSettings = Field(default_factory=WarningSettings)
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)
    approval: ApprovalSettings = Field(default_factory=ApprovalSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def from_toml(cls, path: str | Path) -> "AdminConfig":
        """Load configuration directly from a TOML file (e.g. config.toml)."""
        with Path(path).open("rb") as fp:
            data: dict[str, Any] = tomllib.load(fp)
        return cls.model_validate(data)


class Config(BaseModel):
    """OpsMesh Driver config adapter supporting QQ_ADMIN_CONFIG or QQ_ADMIN__*."""

    model_config = ConfigDict(extra="ignore")

    qq_admin_config: str = ""
    qq_admin: AdminConfig = Field(default_factory=AdminConfig)

    def resolve(self) -> AdminConfig:
        if self.qq_admin_config.strip():
            toml_path = Path(self.qq_admin_config.strip())
            if toml_path.is_file():
                return AdminConfig.from_toml(toml_path)
        return self.qq_admin


__all__ = [
    "AdminConfig",
    "AdminSettings",
    "AgentSettings",
    "ApprovalSettings",
    "Config",
    "EscalationRule",
    "EscalationSettings",
    "GroupApprovalPolicy",
    "IdentitySettings",
    "JevSettings",
    "LoggingSettings",
    "ModerationSettings",
    "PluginSettings",
    "SafeguardSettings",
    "WarningSettings",
]
