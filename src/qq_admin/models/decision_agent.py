"""System 2 Agent 1: DecisionAgent using OpenAI Responses API and .md templates."""

from dataclasses import dataclass, field
from typing import Literal

from agents import (
    Agent,
    InputGuardrailTripwireTriggered,
    ModelSettings,
    OpenAIResponsesModel,
    Runner,
)
from openai import AsyncOpenAI
from openai.types.shared import Reasoning
from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.config import Config
from qq_admin.prompts import load_md, load_toml

from .guardrails import injection_guardrail
from .jev import SafetyReport
from .tools import GROUP_ADMIN_TOOLS


@dataclass(slots=True)
class TurnContext:
    """Minimal per-turn state shared with DecisionAgent tools and guardrails."""

    gateway: Gateway
    group_id: str
    member_id: str
    mode: Literal["auto_moderate", "admin_command"] = "auto_moderate"
    report: SafetyReport | None = None
    executed_actions: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)


class DecisionOutcome(BaseModel):
    """Structured output returned by DecisionAgent for ReplyAgent consumption."""

    action_taken: bool = False
    should_reply: bool = False
    scenario: str = Field(
        default="moderation_action",
        description="Event scenario passed to ReplyAgent.",
    )
    target_member_id: str = ""
    executed_actions: list[str] = Field(default_factory=list)
    summary: str = ""


class DecisionAgent:
    """Stateless tool-calling decision runner over OpenAI Responses API."""

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
            temperature=0.0, reasoning=Reasoning(effort=self.config.reasoning_effort)
        )

    async def execute(
        self,
        prompt: str,
        *,
        context: TurnContext,
        bot_role: str = "admin",
        sender_role: str = "member",
    ) -> DecisionOutcome:
        """Execute one stateless moderation decision turn via Responses API."""
        if self._client is None:
            return DecisionOutcome(
                action_taken=False,
                should_reply=False,
                target_member_id=context.member_id,
                summary="OpenAI client unavailable.",
            )

        from qq_admin.modules.audit import AUDIT

        role_policy = str(
            load_toml("notices.toml").get("role_policy", {}).get(bot_role, "")
        )
        template_name = (
            "decision_admin.md"
            if context.mode == "admin_command"
            else "decision_auto.md"
        )
        instructions = load_md(
            template_name,
            group_id=context.group_id,
            bot_role=bot_role,
            role_policy=role_policy,
            member_id=context.member_id,
            sender_role=sender_role,
            recent_ops=AUDIT.count_member_actions(
                context.group_id, context.member_id, within_hours=24.0
            ),
            jev_summary=context.report.summary() if context.report else "none",
        )

        agent = Agent[TurnContext](
            name="QQGroupDecisionAgent",
            instructions=instructions,
            model=OpenAIResponsesModel(
                model=self.config.model, openai_client=self._client
            ),
            model_settings=self._model_settings(),
            tools=GROUP_ADMIN_TOOLS,
            input_guardrails=[injection_guardrail],
            output_type=DecisionOutcome,
        )

        try:
            result = await Runner.run(
                agent,
                input=prompt,
                context=context,
                max_turns=self.config.max_turns,
            )
        except InputGuardrailTripwireTriggered:
            return DecisionOutcome(
                action_taken=False,
                should_reply=False,
                scenario="injection_blocked",
                target_member_id=context.member_id,
                summary="Blocked by Jev prompt-injection input guardrail.",
            )

        raw = result.final_output
        outcome = (
            raw
            if isinstance(raw, DecisionOutcome)
            else DecisionOutcome(
                action_taken=bool(context.executed_actions),
                should_reply=bool(context.executed_actions),
                target_member_id=context.member_id,
                summary=str(raw or ""),
            )
        )
        outcome.executed_actions = list(context.executed_actions)
        if context.executed_actions:
            outcome.action_taken = True
        if not outcome.target_member_id:
            outcome.target_member_id = context.member_id
        return outcome


__all__ = ["DecisionAgent", "DecisionOutcome", "TurnContext"]
