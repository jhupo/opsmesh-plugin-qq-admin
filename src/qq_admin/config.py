"""Partitioned Pydantic v2 configuration models for qq_admin plugin."""

from pydantic import BaseModel, ConfigDict, Field


class GroupSwitchConfig(BaseModel):
    """Per-group enable/disable policy."""

    model_config = ConfigDict(extra="ignore")

    enabled_by_default: bool = True
    enabled_groups: set[str] = Field(default_factory=set)
    disabled_groups: set[str] = Field(default_factory=set)


class SafeguardConfig(BaseModel):
    """Hard safety rails protecting owners, admins, and daily quotas."""

    model_config = ConfigDict(extra="ignore")

    protected_openids: set[str] = Field(default_factory=set)
    min_mute_seconds: int = Field(default=60, ge=1)
    max_mute_seconds: int = Field(default=2_592_000, ge=60)
    daily_mute_quota: int = Field(default=30, ge=1)
    daily_kick_quota: int = Field(default=10, ge=1)
    daily_blacklist_quota: int = Field(default=10, ge=1)
    daily_approval_quota: int = Field(default=100, ge=1)
    target_cooldown_seconds: int = Field(default=15, ge=0)
    bot_role_cache_ttl_seconds: int = Field(default=300, ge=5)


class WarningPolicyConfig(BaseModel):
    """Sliding-window violation tracking and automatic escalation ladder."""

    model_config = ConfigDict(extra="ignore")

    window_seconds: int = Field(default=86_400, ge=60)
    mute_threshold: int = Field(default=2, ge=1)
    mute_duration_seconds: int = Field(default=600, ge=60)
    kick_threshold: int = Field(default=4, ge=2)
    kick_with_blacklist: bool = False


class AutoApproveConfig(BaseModel):
    """Join-request auto-approval and optional polling reconciliation settings."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    pass_keywords: list[str] = Field(default_factory=list)
    trusted_inviter_openids: set[str] = Field(default_factory=set)
    reject_on_risk_tips: bool = True
    reject_reason: str = (
        "Automatic join verification failed. Please contact a group admin."
    )
    poll_interval_seconds: int = Field(default=0, ge=0)


class AuditConfig(BaseModel):
    """Structured audit ring and optional snapshot persistence."""

    model_config = ConfigDict(extra="ignore")

    max_records_per_group: int = Field(default=500, ge=10)
    snapshot_path: str | None = None


class QQAdminConfig(BaseModel):
    """Top-level configuration model loaded via opsmesh.plugin.get_plugin_config."""

    model_config = ConfigDict(extra="ignore")

    superusers: set[str] = Field(default_factory=set)
    group_switch: GroupSwitchConfig = Field(default_factory=GroupSwitchConfig)
    safeguard: SafeguardConfig = Field(default_factory=SafeguardConfig)
    warning: WarningPolicyConfig = Field(default_factory=WarningPolicyConfig)
    auto_approve: AutoApproveConfig = Field(default_factory=AutoApproveConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    # Convenience flat env overrides (QQ_ADMIN_*)
    qq_admin_enabled_by_default: bool | None = None
    qq_admin_protected_openids: set[str] | None = None
    qq_admin_daily_kick_quota: int | None = None
    qq_admin_daily_mute_quota: int | None = None
    qq_admin_auto_approve_enabled: bool | None = None

    def model_post_init(self, context: object, /) -> None:
        if self.qq_admin_enabled_by_default is not None:
            self.group_switch.enabled_by_default = self.qq_admin_enabled_by_default
        if self.qq_admin_protected_openids is not None:
            self.safeguard.protected_openids |= set(self.qq_admin_protected_openids)
        if self.qq_admin_daily_kick_quota is not None:
            self.safeguard.daily_kick_quota = self.qq_admin_daily_kick_quota
        if self.qq_admin_daily_mute_quota is not None:
            self.safeguard.daily_mute_quota = self.qq_admin_daily_mute_quota
        if self.qq_admin_auto_approve_enabled is not None:
            self.auto_approve.enabled = self.qq_admin_auto_approve_enabled


__all__ = [
    "AuditConfig",
    "AutoApproveConfig",
    "GroupSwitchConfig",
    "QQAdminConfig",
    "SafeguardConfig",
    "WarningPolicyConfig",
]
