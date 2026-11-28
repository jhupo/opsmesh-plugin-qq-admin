"""ReplyComposer (Agent 2): natural, context-aware group reply phrasing."""

import asyncio
import json

from agents import (
    Agent,
    ModelSettings,
    OutputGuardrailTripwireTriggered,
    RunConfig,
    RunContextWrapper,
    Runner,
)
from openai import AsyncOpenAI
from opsmesh.log import logger

from qq_admin.config import AgentSettings
from qq_admin.resources import PromptCatalog

from .guardrails import reply_guardrail
from .planner import build_sdk_model
from .schemas import ReplySpec


def render_composer_instructions(
    ctx: RunContextWrapper[ReplySpec], _agent: Agent[ReplySpec]
) -> str:
    """Inject live group state and persona prompt so ReplyComposer phrases freely."""
    spec = ctx.context
    cfg = spec.runtime.config
    composer_cfg = spec.runtime.catalog.composer
    persona = (
        cfg.agent.reply_persona.strip() or str(composer_cfg.get("persona", "")).strip()
    )

    sf = cfg.safeguard
    mute_limit = "unlimited" if spec.bot_role == "owner" else str(sf.daily_mute_limit)
    kick_limit = "unlimited" if spec.bot_role == "owner" else str(sf.daily_kick_limit)

    return str(composer_cfg.get("instructions", "")).format(
        persona=persona,
        group_id=spec.group_id,
        bot_role=spec.bot_role,
        scenario=spec.scenario,
        actor_id=spec.actor_id,
        actor_role=spec.actor_role,
        target_id=spec.target_id or "-",
        mute_count=spec.runtime.state.daily_count(spec.group_id, "mute"),
        mute_limit=mute_limit,
        kick_count=spec.runtime.state.daily_count(spec.group_id, "kick"),
        kick_limit=kick_limit,
    )


class ReplyComposer:
    """Reusable Agent 2 generating natural, non-repetitive moderation replies."""

    def __init__(
        self,
        settings: AgentSettings,
        catalog: PromptCatalog,
        *,
        openai_client: AsyncOpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self._openai_client = openai_client
        self._agent: Agent[ReplySpec] | None = None

    def bind_client(self, client: AsyncOpenAI | None) -> None:
        self._openai_client = client
        self._agent = None

    def _get_agent(self) -> Agent[ReplySpec]:
        if self._agent is None:
            self._agent = Agent[ReplySpec](
                name="QQGroupReplyComposer",
                model=build_sdk_model(
                    self.settings,
                    self.settings.effective_reply_model,
                    self._openai_client,
                ),
                model_settings=ModelSettings(
                    temperature=self.settings.reply_temperature
                ),
                instructions=render_composer_instructions,
                tools=[],
                output_guardrails=[reply_guardrail],
            )
        return self._agent

    async def compose(self, spec: ReplySpec) -> str:
        """Compose a contextual reply or cleanly return spec.fallback."""
        if not self.settings.enabled:
            return spec.fallback

        payload = {
            "scenario": spec.scenario,
            "group_id": spec.group_id,
            "bot_role": spec.bot_role,
            "actor_id": spec.actor_id,
            "actor_role": spec.actor_role,
            "target_id": spec.target_id,
            "executed_actions": spec.executed_actions,
            "facts": spec.facts,
        }
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                result = await Runner.run(
                    self._get_agent(),
                    json.dumps(payload, ensure_ascii=False),
                    context=spec,
                    max_turns=2,
                    run_config=RunConfig(workflow_name="qq-admin-composer"),
                )
        except OutputGuardrailTripwireTriggered:
            logger.warning(f"qq_admin reply guardrail blocked text in {spec.group_id}")
            return spec.fallback
        except (TimeoutError, Exception) as exc:
            logger.warning(f"qq_admin ReplyComposer failed (using fallback): {exc}")
            return spec.fallback

        text = str(result.final_output or "").strip()
        return text or spec.fallback


__all__ = ["ReplyComposer", "render_composer_instructions"]
