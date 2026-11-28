"""ServiceManager: typed holder of shared OpenAI/Jev clients and feature modules."""

from typing import Any

from openai import AsyncOpenAI

from qq_admin.config import Config
from qq_admin.exception import ConfigError
from qq_admin.models import AsyncTypeSafeClient, DecisionAgent, Jev, ReplyAgent
from qq_admin.modules import (
    ApprovalModule,
    AuditModule,
    EscalationModule,
    GatewayProvider,
    IdentityModule,
    ModerationModule,
    SafeguardModule,
    WarningModule,
)
from qq_admin.resources import PromptCatalog
from qq_admin.store import ConfigStore


def _build_openai_client(cfg: Config) -> AsyncOpenAI | None:
    api_key = cfg.effective_openai_key
    if not api_key:
        return None
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": cfg.timeout_seconds}
    if cfg.openai_base_url.strip():
        kwargs["base_url"] = cfg.openai_base_url.strip()
    return AsyncOpenAI(**kwargs)


class ServiceManager:
    """Holds shared Jev/OpenAI clients, both Responses agents, and feature modules."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        store: ConfigStore | None = None,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        cfg = config or Config()
        self.config = cfg
        self.store = store or (
            ConfigStore.from_toml(cfg.config_path)
            if cfg.config_path.strip()
            else ConfigStore()
        )
        self.catalog = PromptCatalog.load(cfg.prompts_path or None)

        self._owns_openai = openai_client is None
        self._openai_client = openai_client or _build_openai_client(cfg)

        self.jev = Jev(cfg, client=jev_client)
        self.decision_agent = DecisionAgent(cfg, client=self._openai_client)
        self.reply_agent = ReplyAgent(cfg, client=self._openai_client)

        self.identity = IdentityModule(self.store)
        self.audit = AuditModule(self.store)
        self.warning = WarningModule(self.store)
        self.escalation = EscalationModule(self.store, self.audit)
        self.safeguard = SafeguardModule(self.store, self.identity, self.escalation)
        self.moderation = ModerationModule(self.store, self)
        self.approval = ApprovalModule(self.store, self)

    def is_group_enabled(self, group_id: str) -> bool:
        return self.store.is_group_enabled(group_id)

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        self.store.set_group_enabled(group_id, enabled)

    def configurable_modules(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "safeguard": self.safeguard,
            "warning": self.warning,
            "escalation": self.escalation,
            "moderation": self.moderation,
            "approval": self.approval,
            "audit": self.audit,
        }

    def module(self, name: str):
        module = self.configurable_modules().get(name)
        if module is None:
            raise ConfigError(f"Unknown module: {name}")
        return module

    def start(self, gateways: GatewayProvider) -> None:
        self.approval.start_polling(gateways)

    async def shutdown(self) -> None:
        await self.approval.stop_polling()
        await self.jev.close()
        if self._owns_openai and self._openai_client is not None:
            await self._openai_client.close()
            self._openai_client = None


_active_manager: ServiceManager | None = None


def set_manager(manager: ServiceManager) -> ServiceManager:
    global _active_manager
    _active_manager = manager
    return manager


def get_manager() -> ServiceManager:
    global _active_manager
    if _active_manager is None:
        _active_manager = ServiceManager()
    return _active_manager


__all__ = ["ServiceManager", "get_manager", "set_manager"]
