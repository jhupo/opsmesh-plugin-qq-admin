"""AdminServices container wiring all stateful group-admin domain services."""

from dataclasses import dataclass

from qq_admin.config import QQAdminConfig
from qq_admin.store import InMemoryStateStore, StateStoreProtocol

from .audit import AuditService
from .auto_approve import AutoApproveService
from .identity import IdentityService
from .moderation import ModerationService
from .safeguard import SafeguardService
from .warning import WarningService


@dataclass(slots=True)
class AdminServices:
    """Explicit dependency container injected into matchers and standalone tools."""

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


__all__ = [
    "AdminServices",
    "AuditService",
    "AutoApproveService",
    "IdentityService",
    "ModerationService",
    "SafeguardService",
    "WarningService",
]
