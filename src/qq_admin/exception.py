"""Domain exception hierarchy for qq_admin permissions and safeguards."""


class QQAdminError(Exception):
    """Base structured domain error raised by qq_admin services and public APIs."""

    code: str = "QQ_ADMIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        if code is not None:
            self.code = code


class GroupAdminDisabledError(QQAdminError):
    code = "GROUP_ADMIN_DISABLED"


class PermissionDeniedError(QQAdminError):
    code = "PERMISSION_DENIED"


class BotRoleInsufficientError(QQAdminError):
    code = "BOT_ROLE_INSUFFICIENT"


class TargetProtectedError(QQAdminError):
    code = "TARGET_PROTECTED"


class QuotaExceededError(QQAdminError):
    code = "QUOTA_EXCEEDED"


class CooldownActiveError(QQAdminError):
    code = "COOLDOWN_ACTIVE"


__all__ = [
    "BotRoleInsufficientError",
    "CooldownActiveError",
    "GroupAdminDisabledError",
    "PermissionDeniedError",
    "QQAdminError",
    "QuotaExceededError",
    "TargetProtectedError",
]
