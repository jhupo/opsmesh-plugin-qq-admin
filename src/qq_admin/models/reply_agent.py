"""System 2 Agent 2: ReplyAgent for stateless persona-driven replies."""

from dataclasses import dataclass, field
import json
import os
from typing import TYPE_CHECKING, Any

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    OutputGuardrailTripwireTriggered,
    Runner,
)
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from qq_admin.config import ReplyAgentConfig

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
    """Stateless OpenAI Agents SDK reply composer with ReplyAgentConfig."""

    def __init__(
        self,
        config: ReplyAgentConfig,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None

    @property
    def is_ready(self) -> bool:
        if self._client is not None:
            return True
        return bool(self.config.secret_value or os.environ.get("OPENAI_API_KEY", ""))

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            api_key = self.config.secret_value or os.environ.get("OPENAI_API_KEY", "")
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "timeout": self.config.timeout_seconds,
            }
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = AsyncOpenAI(**kwargs)
            self._owns_client = True
        return self._client

    def _build_model(self) -> OpenAIChatCompletionsModel | OpenAIResponsesModel:
        client = self._get_client()
        if self.config.use_chat_completions:
            return OpenAIChatCompletionsModel(
                model=self.config.model, openai_client=client
            )
        return OpenAIResponsesModel(model=self.config.model, openai_client=client)

    def _model_settings(self) -> ModelSettings:
        reasoning = (
            Reasoning(effort=self.config.reasoning_effort)
            if self.config.reasoning_effort
            else None
        )
        return ModelSettings(temperature=self.config.temperature, reasoning=reasoning)

    async def execute(self, spec: ReplySpec) -> str:
        """Generate one natural, non-repetitive group admin reply."""
        if not self.is_ready:
            return spec.fallback

        sg_cfg = spec.manager.safeguard.config(spec.group_id)
        daily = spec.manager.safeguard.daily_counts(spec.group_id)
        catalog = spec.manager.catalog
        persona = self.config.persona.strip() or catalog.composer_persona()
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
            model=self._build_model(),
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

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None


__all__ = ["ReplyAgent", "ReplySpec"]
