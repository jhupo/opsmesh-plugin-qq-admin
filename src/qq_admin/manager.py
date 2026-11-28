"""ServiceManager: the single typed holder of models and feature modules."""

from openai import AsyncOpenAI

from qq_admin.config import AgentConfig, ConfigStore, JevConfig
from qq_admin.exception import ConfigError
from qq_admin.models import DecisionAgent, Jev, ReplyAgent
from qq_admin.models.jev import AsyncTypeSafeClient
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


class ServiceManager:
    """Holds the Jev client, both agents, and every feature module."""

    def __init__(
        self,
        *,
        jev_config: JevConfig | None = None,
        agent_config: AgentConfig | None = None,
        store: ConfigStore | None = None,
        prompts_path: str | None = None,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        agent_config = agent_config or AgentConfig()
        self.store = store or ConfigStore()
        self.catalog = PromptCatalog.load(prompts_path)

        self.jev = Jev(jev_config or JevConfig(), client=jev_client)
        self.decision_agent = DecisionAgent(
            agent_config, self.store, client=openai_client
        )
        self.reply_agent = ReplyAgent(agent_config, self.store, client=openai_client)

        self.identity = IdentityModule(self.store)
        self.audit = AuditModule(self.store)
        self.warning = WarningModule(self.store)
        self.escalation = EscalationModule(self.store, self.audit)
        self.safeguard = SafeguardModule(self.store, self.identity, self.escalation)
        self.moderation = ModerationModule(self.store, self)
        self.approval = ApprovalModule(self.store, self)

    # ---- group switch ----
    def is_group_enabled(self, group_id: str) -> bool:
        return self.store.is_group_enabled(group_id)

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        self.store.set_group_enabled(group_id, enabled)

    # ---- online module configuration ----
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

    # ---- agent sessions ----
    async def reset_group_sessions(self, group_id: str) -> None:
        await self.decision_agent.reset_session(f"decision:{group_id}")
        await self.reply_agent.reset_session(f"reply:{group_id}")

    # ---- lifecycle ----
    def start(self, gateways: GatewayProvider) -> None:
        self.approval.start_polling(gateways)

    async def shutdown(self) -> None:
        await self.approval.stop_polling()
        await self.jev.close()
        await self.decision_agent.close()
        await self.reply_agent.close()


__all__ = ["ServiceManager"]
