"""ServiceManager: global MANAGER holding shared Jev & ReplyAgent clients."""

from typing import Any

from openai import AsyncOpenAI

from qq_admin.config import Config
from qq_admin.models import AsyncTypeSafeClient, Jev, ReplyAgent
from qq_admin.store import CONFIG_STORE, ConfigStore


def _build_openai_client(cfg: Config) -> AsyncOpenAI | None:
    api_key = cfg.openai_api_key.strip()
    if not api_key:
        return None
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": cfg.timeout_seconds}
    if cfg.openai_base_url.strip():
        kwargs["base_url"] = cfg.openai_base_url.strip()
    return AsyncOpenAI(**kwargs)


class ServiceManager:
    """Holds base Config, shared Jev/OpenAI clients, and multi-group switch."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        store: ConfigStore | None = None,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        self.store = CONFIG_STORE
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
        """Apply plugin Config, sync CONFIG_STORE, and rebuild model runners."""
        if store is not None:
            CONFIG_STORE.reset(store.raw_data(), path=store.path)
        elif config.config_path.strip():
            CONFIG_STORE.reset(path=config.config_path)
            config = Config.model_validate(
                {**config.model_dump(), **CONFIG_STORE.raw_data()}
            )
        else:
            CONFIG_STORE.reset()

        self.config = config
        self.store = CONFIG_STORE
        self._owns_openai = openai_client is None
        self._openai_client = openai_client or _build_openai_client(config)

        self.jev = Jev(config, client=jev_client)
        self.reply_agent = ReplyAgent(config, client=self._openai_client)
        return self

    def is_group_enabled(self, group_id: str) -> bool:
        return CONFIG_STORE.is_group_enabled(
            group_id, default=self.config.default_group_enabled
        )

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        CONFIG_STORE.set_group_enabled(group_id, enabled)

    def managed_groups(self) -> list[str]:
        return CONFIG_STORE.known_groups()

    async def shutdown(self) -> None:
        await self.jev.close()
        if self._owns_openai and self._openai_client is not None:
            await self._openai_client.close()
            self._openai_client = None


MANAGER = ServiceManager()

__all__ = ["MANAGER", "ServiceManager"]
