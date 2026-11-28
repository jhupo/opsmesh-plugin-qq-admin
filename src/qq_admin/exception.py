"""Semantic exceptions for opsmesh-plugin-qq-admin."""


class QQAdminError(Exception):
    """Base exception for all QQ group administration errors."""


class BotNotAdminError(QQAdminError):
    """Raised when the bot is neither owner nor admin in the target group."""


class PermissionDeniedError(QQAdminError):
    """Raised when a command caller lacks required group or global privileges."""


class SafeguardBlockedError(QQAdminError):
    """Raised when an action is rejected by the role-aware safeguard policy."""

    def __init__(self, message: str, *, step: str = "") -> None:
        super().__init__(message)
        self.step = step


__all__ = [
    "BotNotAdminError",
    "PermissionDeniedError",
    "QQAdminError",
    "SafeguardBlockedError",
]
