"""ServiceManager: global holder of shared OpenAI/Jev clients and feature modules."""

from typing import Any

from openai import AsyncOpenAI

from qq_admin.config import Config
from qq_admin.exception import ConfigError
from qq_admin.models import AsyncTypeSafeClient, DecisionAgent, Jev, ReplyAgent
from qq_admin.modules import (
    ApprovalModule,
    AuditModule,
    EscalationModule,
    IdentityModule,
    ModerationModule,
    SafeguardModule,
    WarningModule,
)
from qq_admin.prompts import PromptCatalog
from qq_admin.store import ConfigStore


def _build_openai_client(cfg: Config) -> AsyncOpenAI | None:
    api_key = cfg.openai_api_key.strip()
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
        self.catalog = PromptCatalog.load()
        self._owns_openai = False
        self._openai_client: AsyncOpenAI | None = None
        self.setup(
            config or Config(),
            store=store,
            jev_client=jev_client,
            openai_client=openai_client,
        )

    def setup(
        self,
        config: Config,
        *,
        store: ConfigStore | None = None,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> "ServiceManager":
        """Apply plugin Config and reinitialize clients and modules in place."""
        if config.config_path.strip() and store is None:
            store = ConfigStore.from_toml(config.config_path)
            config = Config.model_validate({**config.model_dump(), **store.raw_data()})

        self.config = config
        self.store = store or ConfigStore()
        self._owns_openai = openai_client is None
        self._openai_client = openai_client or _build_openai_client(config)

        self.jev = Jev(config, client=jev_client)
        self.decision_agent = DecisionAgent(config, client=self._openai_client)
        self.reply_agent = ReplyAgent(config, client=self._openai_client)

        self.identity = IdentityModule(self.store)
        self.audit = AuditModule(self.store)
        self.warning = WarningModule(self.store)
        self.escalation = EscalationModule(self.store, self.audit)
        self.safeguard = SafeguardModule(self.store, self.identity, self.escalation)
        self.moderation = ModerationModule(self.store, self)
        self.approval = ApprovalModule(self.store, self)
        return self

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

    async def shutdown(self) -> None:
        await self.jev.close()
        if self._owns_openai and self._openai_client is not None:
            await self._openai_client.close()
            self._openai_client = None


manager = ServiceManager()

__all__ = ["ServiceManager", "manager"]
