"""AdminServices container and runtime accessor wiring all domain services."""

from dataclasses import dataclass

from qq_admin.config import QQAdminConfig
from qq_admin.store import InMemoryStateStore, StateStoreProtocol

from .audit import AuditService as AuditService
from .auto_approve import AutoApproveService as AutoApproveService
from .identity import IdentityService as IdentityService
from .moderation import ModerationService as ModerationService
from .safeguard import SafeguardService as SafeguardService
from .warning import WarningService as WarningService


@dataclass(slots=True)
class AdminServices:
    """Explicit dependency container injected into matchers and public functions."""

    config: QQAdminConfig
    store: StateStoreProtocol
    identity: IdentityService
    safeguard: SafeguardService
    warning: WarningService
    audit: AuditService
    moderation: ModerationService
    auto_approve: AutoApproveService

    @classmethod
    def create(
        cls,
        config: QQAdminConfig | None = None,
        store: StateStoreProtocol | None = None,
    ) -> "AdminServices":
        cfg = config if config is not None else QQAdminConfig()
        state_store = (
            store
            if store is not None
            else InMemoryStateStore(snapshot_path=cfg.audit.snapshot_path)
        )
        identity = IdentityService(cfg, state_store)
        safeguard = SafeguardService(cfg, state_store)
        warning = WarningService(cfg, state_store)
        audit = AuditService(cfg, state_store)
        moderation = ModerationService(
            config=cfg,
            store=state_store,
            identity=identity,
            safeguard=safeguard,
            warning=warning,
            audit=audit,
        )
        auto_approve = AutoApproveService(
            config=cfg, moderation=moderation, audit=audit
        )
        return cls(
            config=cfg,
            store=state_store,
            identity=identity,
            safeguard=safeguard,
            warning=warning,
            audit=audit,
            moderation=moderation,
            auto_approve=auto_approve,
        )


_runtime_services: AdminServices | None = None


def set_services(services: AdminServices) -> None:
    """Bind the active AdminServices instance for matchers and public API calls."""
    global _runtime_services
    _runtime_services = services


def get_services() -> AdminServices:
    """Return the active AdminServices instance (lazily created if unset)."""
    global _runtime_services
    if _runtime_services is None:
        _runtime_services = AdminServices.create()
    return _runtime_services


from .moderation import add_blacklist as add_blacklist
from .moderation import approve_join_request as approve_join_request
from .moderation import clear_warnings as clear_warnings
from .moderation import decline_join_request as decline_join_request
from .moderation import get_audit_log as get_audit_log
from .moderation import get_bot_state as get_bot_state
from .moderation import get_group_info as get_group_info
from .moderation import get_member as get_member
from .moderation import get_mute_setting as get_mute_setting
from .moderation import kick_member as kick_member
from .moderation import list_blacklist as list_blacklist
from .moderation import list_join_requests as list_join_requests
from .moderation import list_members as list_members
from .moderation import mute_member as mute_member
from .moderation import recall_message as recall_message
from .moderation import remove_blacklist as remove_blacklist
from .moderation import set_group_enabled as set_group_enabled
from .moderation import unmute_member as unmute_member
from .moderation import warn_member as warn_member
