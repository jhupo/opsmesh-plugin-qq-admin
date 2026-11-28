"""Exceptions for opsmesh-plugin-qq-admin."""


class QQAdminError(Exception):
    """Base exception for all QQ group administration errors."""


class BotNotAdminError(QQAdminError):
    """Raised when the bot is not an admin or owner in the target group."""


class PermissionDeniedError(QQAdminError):
    """Raised when a command operator lacks required group or global privileges."""


class GuardBlockedError(QQAdminError):
    """Raised when an action is rejected by the role-aware safeguard chain."""

    def __init__(self, message: str, *, step: str = "") -> None:
        super().__init__(message)
        self.step = step


__all__ = [
    "BotNotAdminError",
    "GuardBlockedError",
    "PermissionDeniedError",
    "QQAdminError",
]
