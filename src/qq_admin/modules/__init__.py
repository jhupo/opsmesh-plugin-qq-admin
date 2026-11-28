"""Self-contained group administration feature modules."""

from .approval import ApprovalConfig, ApprovalModule, GatewayProvider
from .audit import AuditConfig, AuditModule, AuditRecord
from .duration import MuteDuration, format_duration, parse_duration
from .escalation import EscalationConfig, EscalationModule, EscalationRule
from .identity import IdentityConfig, IdentityModule, MinimumRole, PermissionTrace
from .moderation import (
    ActionOutcome,
    MessageAssessment,
    MessageSnapshot,
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
    "GatewayProvider",
    "IdentityConfig",
    "IdentityModule",
    "MessageAssessment",
    "MessageSnapshot",
    "MinimumRole",
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
