"""Core enumerations and role ranking helpers for qq_admin."""

from enum import StrEnum


class RoleTier(StrEnum):
    """Normalized group/system authority tier."""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"
    SUPERUSER = "superuser"


_ROLE_RANK: dict[RoleTier, int] = {
    RoleTier.MEMBER: 0,
    RoleTier.ADMIN: 1,
    RoleTier.OWNER: 2,
    RoleTier.SUPERUSER: 3,
}


def parse_role_tier(raw: str | RoleTier | None) -> RoleTier:
    if isinstance(raw, RoleTier):
        return raw
    normalized = str(raw or "member").strip().lower()
    if normalized == "superuser":
        return RoleTier.SUPERUSER
    if normalized == "owner":
        return RoleTier.OWNER
    if normalized == "admin":
        return RoleTier.ADMIN
    return RoleTier.MEMBER


def role_rank(tier: str | RoleTier | None) -> int:
    return _ROLE_RANK[parse_role_tier(tier)]


class ViolationType(StrEnum):
    """Categorized violation kinds tracked by WarningService."""

    SPAM = "spam"
    ABUSE = "abuse"
    AD = "ad"
    OTHER = "other"


class EscalationAction(StrEnum):
    """Automatic punishment ladder step triggered by sliding-window warnings."""

    WARN_ONLY = "warn_only"
    AUTO_MUTE = "auto_mute"
    AUTO_KICK = "auto_kick"


class AuditSource(StrEnum):
    """Origin of a group-admin operation."""

    COMMAND = "command"
    API = "api"
    AUTO = "auto"


class AuditStatus(StrEnum):
    """Outcome status recorded in structured audit logs."""

    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


__all__ = [
    "AuditSource",
    "AuditStatus",
    "EscalationAction",
    "RoleTier",
    "ViolationType",
    "parse_role_tier",
    "role_rank",
]
