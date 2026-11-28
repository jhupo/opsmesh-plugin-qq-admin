"""Domain exceptions for QQ Official v2 group management."""


class QQAdminError(Exception):
    """Base exception for qq_admin errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


class BotNotAdminError(QQAdminError):
    """Raised when the bot lacks admin/owner role in the target group."""


class HierarchyError(QQAdminError):
    """Raised when operator role cannot manage the target member role."""


class GroupTargetRequiredError(QQAdminError):
    """Raised when an event is not associated with any QQ group_openid."""
