"""Self-contained group administration feature modules and global singletons."""

from typing import Any

from qq_admin.exception import ConfigError

from .approval import APPROVAL, ApprovalConfig, ApprovalModule
from .audit import AUDIT, AuditConfig, AuditModule, AuditRecord
from .duration import MuteDuration, format_duration, parse_duration
from .escalation import ESCALATION, EscalationConfig, EscalationModule, EscalationRule
from .identity import IDENTITY, IdentityConfig, IdentityModule, PermissionTrace
from .moderation import (
    MODERATION,
    ActionOutcome,
    ModerationConfig,
    ModerationModule,
    RouteKind,
    WarningCategory,
)
from .safeguard import SAFEGUARD, PolicyVerdict, SafeguardConfig, SafeguardModule
from .warning import WARNING, WarningConfig, WarningModule

MODULES: dict[str, Any] = {
    "identity": IDENTITY,
    "safeguard": SAFEGUARD,
    "warning": WARNING,
    "escalation": ESCALATION,
    "moderation": MODERATION,
    "approval": APPROVAL,
    "audit": AUDIT,
}


def get_module(name: str) -> Any:
    """Look up a configurable feature module singleton by name."""
    module = MODULES.get(name)
    if module is None:
        raise ConfigError(f"Unknown module: {name}")
    return module


def reset_modules() -> None:
    """Clear in-memory caches/counters across all global module singletons."""
    IDENTITY.clear()
    AUDIT.clear()
    WARNING.clear()
    SAFEGUARD.clear()


__all__ = [
    "APPROVAL",
    "AUDIT",
    "ESCALATION",
    "IDENTITY",
    "MODERATION",
    "MODULES",
    "SAFEGUARD",
    "WARNING",
    "ActionOutcome",
    "ApprovalConfig",
    "ApprovalModule",
    "AuditConfig",
    "AuditModule",
    "AuditRecord",
    "EscalationConfig",
    "EscalationModule",
    "EscalationRule",
    "IdentityConfig",
    "IdentityModule",
    "ModerationConfig",
    "ModerationModule",
    "MuteDuration",
    "PermissionTrace",
    "PolicyVerdict",
    "RouteKind",
    "SafeguardConfig",
    "SafeguardModule",
    "WarningCategory",
    "WarningConfig",
    "WarningModule",
    "format_duration",
    "get_module",
    "parse_duration",
    "reset_modules",
]
