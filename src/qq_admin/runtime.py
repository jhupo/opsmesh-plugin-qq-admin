"""AdminRuntime composition root owning collaborators and async lifecycles."""

import asyncio
from typing import Any

from openai import AsyncOpenAI
from opsmesh import get_gateways
from opsmesh.log import logger
from qq import Gateway
from typesafe_sdk import AsyncTypeSafeClient

from .agents import DecisionPlanner, ReplyComposer
from .config import AdminConfig
from .jev import JevEvaluator
from .moderation import GroupModerator, JoinApprover, SafeguardPolicy
from .resources import PromptCatalog
from .state import GroupStateStore


class AdminRuntime:
    """Wires all domain collaborators and manages external client lifecycles."""

    def __init__(
        self,
        config: AdminConfig,
        *,
        jev_client: AsyncTypeSafeClient | None = None,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self.catalog = PromptCatalog.load(config.plugin.prompts_path)
        self.state = GroupStateStore(config)
        self.jev = JevEvaluator(config.jev, self.catalog, client=jev_client)
        self.policy = SafeguardPolicy(config, self.state)
        self.moderator = GroupModerator(config, self.state, self.policy, self.catalog)
        self.approver = JoinApprover(
            config, self.state, self.policy, self.jev, self.catalog
        )

        self._openai_client: AsyncOpenAI | None = openai_client
        self._owns_openai = False
        if self._openai_client is None and self._needs_custom_openai():
            self._openai_client = self._create_openai_client()
            self._owns_openai = True

        self.planner = DecisionPlanner(
            config.agent, self.catalog, openai_client=self._openai_client
        )
        self.composer = ReplyComposer(
            config.agent, self.catalog, openai_client=self._openai_client
        )
        self._tasks: list[asyncio.Task[Any]] = []

    def _needs_custom_openai(self) -> bool:
        ag = self.config.agent
        return ag.enabled and bool(
            ag.use_chat_completions or ag.base_url.strip() or ag.secret_value
        )

    def _create_openai_client(self) -> AsyncOpenAI:
        ag = self.config.agent
        return AsyncOpenAI(
            api_key=ag.secret_value or None,
            base_url=ag.base_url.strip() or None,
            timeout=ag.timeout_seconds,
        )

    async def startup(self) -> None:
        """Open external SDK clients and start background maintenance tasks."""
        if not self.config.plugin.enabled:
            return
        await self.jev.open()
        ap = self.config.approval
        if (ap.enabled or ap.groups) and ap.check_interval_seconds > 0:
            self._tasks.append(asyncio.create_task(self._poll_joins_loop()))
        self._tasks.append(asyncio.create_task(self._evict_state_loop()))

    async def shutdown(self) -> None:
        """Cancel background tasks and close owned SDK HTTP clients."""
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        await self.jev.close()
        if self._owns_openai and self._openai_client is not None:
            await self._openai_client.close()
            self._openai_client = None
            self._owns_openai = False

    async def _poll_joins_loop(self) -> None:
        interval = self.config.approval.check_interval_seconds
        while interval > 0:
            try:
                await asyncio.sleep(interval)
                for gw in get_gateways().values():
                    if isinstance(gw, Gateway):
                        await self.approver.poll_all_groups(gw)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"qq_admin join poll loop error: {exc}")

    async def _evict_state_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(600)
                self.state.evict_expired()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"qq_admin eviction loop error: {exc}")


__all__ = ["AdminRuntime"]
