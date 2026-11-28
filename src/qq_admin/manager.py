"""ServiceManager: typed holder of shared OpenAI/Jev clients and feature modules."""

import os
from typing import Any

from openai import AsyncOpenAI

from qq_admin.config import (
    ConfigStore,
    DecisionAgentConfig,
    JevConfig,
    OpenAIConfig,
    ReplyAgentConfig,
)
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


def _build_openai_client(cfg: OpenAIConfig) -> AsyncOpenAI | None:
    api_key = cfg.secret_value or os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": cfg.timeout_seconds}
    if cfg.base_url.strip():
        kwargs["base_url"] = cfg.base_url.strip()
    return AsyncOpenAI(**kwargs)


class ServiceManager:
    """Holds shared Jev/OpenAI clients, both Responses agents, and feature modules."""

    def __init__(
        self,
        *,
        jev_config: JevConfig | None = None,
        openai_config: OpenAIConfig | None = None,
        decision_config: DecisionAgentConfig | None = None,
        reply_config: ReplyAgentConfig | None = None,
        store: ConfigStore | None = None,
        prompts_path: str | None = None,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        self.store = store or ConfigStore()
        self.catalog = PromptCatalog.load(prompts_path)

        oa_cfg = openai_config or OpenAIConfig()
        self._owns_openai = openai_client is None
        self._openai_client = openai_client or _build_openai_client(oa_cfg)

        self.jev = Jev(jev_config or JevConfig(), client=jev_client)
        self.decision_agent = DecisionAgent(
            decision_config or DecisionAgentConfig(), client=self._openai_client
        )
        self.reply_agent = ReplyAgent(
            reply_config or ReplyAgentConfig(), client=self._openai_client
        )

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
