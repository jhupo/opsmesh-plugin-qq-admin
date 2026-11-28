"""System 2 Agent 2: ReplyAgent rendering prompts/reply_agent.md via Responses API."""

from dataclasses import dataclass, field
import json
from typing import Any

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
from qq_admin.prompts import CATALOG

from .guardrails import reply_guardrail


@dataclass(slots=True)
class ReplySpec:
    """Live state snapshot and event facts supplied to ReplyAgent."""

    group_id: str
    bot_role: str
    scenario: str
    actor_id: str = ""
    actor_role: str = "member"
    target_id: str = ""
    categories: list[str] = field(default_factory=list)
    executed_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    fallback: str = ""


class ReplyAgent:
    """Stateless persona-driven reply composer powered by reply_agent.md."""

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
        """Generate one natural, non-repetitive group admin reply."""
        if self._client is None:
            return spec.fallback

        from qq_admin.modules.safeguard import SAFEGUARD

        sg_cfg = SAFEGUARD.config(spec.group_id)
        daily = SAFEGUARD.daily_counts(spec.group_id)
        instructions = CATALOG.reply_prompt(
            group_id=spec.group_id,
            bot_role=spec.bot_role,
            scenario=spec.scenario,
            actor_id=spec.actor_id or "unknown",
            actor_role=spec.actor_role,
            target_id=spec.target_id or "none",
            categories=", ".join(spec.categories) if spec.categories else "none",
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
            "categories": spec.categories,
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
