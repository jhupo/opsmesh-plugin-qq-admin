"""Self-contained group administration feature modules."""

from .approval import ApprovalConfig, ApprovalModule
from .audit import AuditConfig, AuditModule, AuditRecord
from .duration import MuteDuration, format_duration, parse_duration
from .escalation import EscalationConfig, EscalationModule, EscalationRule
from .identity import IdentityConfig, IdentityModule, PermissionTrace
from .moderation import (
    ActionOutcome,
    ModerationConfig,
    ModerationModule,
    WarningCategory,
)
from .safeguard import PolicyVerdict, SafeguardConfig, SafeguardModule
from .warning import WarningConfig, WarningModule

__all__ = [
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
    "SafeguardConfig",
    "SafeguardModule",
    "WarningCategory",
    "WarningConfig",
    "WarningModule",
    "format_duration",
    "parse_duration",
]
