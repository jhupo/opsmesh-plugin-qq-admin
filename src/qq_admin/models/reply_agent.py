"""System 2 Agent 2: ReplyAgent using OpenAI Responses API."""

from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

from agents import (
    Agent,
    ModelSettings,
    OpenAIResponsesModel,
    OutputGuardrailTripwireTriggered,
    Runner,
)
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from qq_admin.config import Config

from .guardrails import reply_guardrail

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager


@dataclass(slots=True)
class ReplySpec:
    """Live state snapshot and event facts supplied to ReplyAgent."""

    manager: "ServiceManager"
    group_id: str
    bot_role: str
    scenario: str
    actor_id: str = ""
    actor_role: str = "member"
    target_id: str = ""
    executed_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    fallback: str = ""


class ReplyAgent:
    """Stateless persona-driven reply composer over OpenAI Responses API."""

    def __init__(
        self,
        config: Config,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self._client = client

    @property
    def is_ready(self) -> bool:
        return self._client is not None

    def _model_settings(self) -> ModelSettings:
        return ModelSettings(
            temperature=0.7, reasoning=Reasoning(effort=self.config.reasoning_effort)
        )

    async def execute(self, spec: ReplySpec) -> str:
        """Generate one natural group admin reply via Responses API."""
        if self._client is None:
            return spec.fallback

        sg_cfg = spec.manager.safeguard.config(spec.group_id)
        daily = spec.manager.safeguard.daily_counts(spec.group_id)
        catalog = spec.manager.catalog
        persona = catalog.composer_persona()
        instructions = catalog.composer_instructions(
            persona=persona,
            group_id=spec.group_id,
            bot_role=spec.bot_role,
            scenario=spec.scenario,
            actor_id=spec.actor_id or "unknown",
            actor_role=spec.actor_role,
            target_id=spec.target_id or "none",
            mute_count=daily["mute"],
            mute_limit=sg_cfg.daily_mute_limit,
            kick_count=daily["kick"],
            kick_limit=sg_cfg.daily_kick_limit,
        )

        agent = Agent[ReplySpec](
            name="QQGroupReplyAgent",
            instructions=instructions,
            model=OpenAIResponsesModel(
                model=self.config.model, openai_client=self._client
            ),
            model_settings=self._model_settings(),
            output_guardrails=[reply_guardrail],
        )

        payload = {
            "scenario": spec.scenario,
            "executed_actions": spec.executed_actions,
            "facts": spec.facts,
        }
        try:
            result = await Runner.run(
                agent,
                input=json.dumps(payload, ensure_ascii=False),
                context=spec,
                max_turns=self.config.max_turns,
            )
            text = str(result.final_output or "").strip()
            return text or spec.fallback
        except OutputGuardrailTripwireTriggered:
            return spec.fallback
        except Exception:
            return spec.fallback


__all__ = ["ReplyAgent", "ReplySpec"]
