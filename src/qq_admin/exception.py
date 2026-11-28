"""Domain exceptions for opsmesh-plugin-qq-admin."""


class QQAdminError(Exception):
    """Base exception for the QQ group administration plugin."""


class ConfigError(QQAdminError):
    """Raised when an online configuration key or value is invalid."""


class BotNotAdminError(QQAdminError):
    """Raised when the bot lacks group admin or owner privileges."""


class PermissionDeniedError(QQAdminError):
    """Raised when a user lacks permission to invoke a command."""


class SafeguardBlockedError(QQAdminError):
    """Raised when a moderation action is blocked by SafeguardModule."""


__all__ = [
    "BotNotAdminError",
    "ConfigError",
    "PermissionDeniedError",
    "QQAdminError",
    "SafeguardBlockedError",
]
