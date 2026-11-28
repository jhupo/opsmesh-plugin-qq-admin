"""DecisionPlanner (Agent 1): deterministic tool orchestration controller."""

import asyncio
import json
from typing import Any

from agents import (
    Agent,
    InputGuardrailTripwireTriggered,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunConfig,
    RunContextWrapper,
    Runner,
)
from openai import AsyncOpenAI
from opsmesh.log import logger

from qq_admin.config import AgentSettings
from qq_admin.resources import PromptCatalog

from .guardrails import injection_guardrail
from .schemas import DecisionOutcome, TurnContext
from .tools import GROUP_ADMIN_TOOLS


def build_sdk_model(
    settings: AgentSettings, model_name: str, client: AsyncOpenAI | None
) -> Any:
    """Return an OpenAIChatCompletionsModel when a shared client is bound."""
    if client is not None and (
        settings.use_chat_completions
        or settings.base_url.strip()
        or settings.secret_value
    ):
        return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
    return model_name


def render_planner_instructions(
    ctx: RunContextWrapper[TurnContext], _agent: Agent[TurnContext]
) -> str:
    """Render role-aware decision instructions from external prompts.toml."""
    turn = ctx.context
    cfg = turn.runtime.catalog.planner
    policy_text = str(
        cfg.get(f"role_policy_{turn.bot_role}", cfg.get("role_policy_member", ""))
    )

    if turn.mode == "admin_command":
        return str(cfg.get("admin_command", "")).format(
            group_id=turn.group_id,
            bot_role=turn.bot_role,
            role_policy=policy_text,
            member_id=turn.member_id,
            sender_role=turn.sender_role,
        )

    recent_ops = turn.runtime.state.count_violations(
        turn.group_id, turn.member_id, within_hours=24.0
    )
    jev_summary = (
        f"violation={turn.assessment.primary_violation}, "
        f"severity={turn.assessment.severity:.2f}, "
        f"confidence={turn.assessment.effective_confidence:.2f}, "
        f"banter={turn.assessment.banter_probability:.2f}"
        if turn.assessment and turn.assessment.status == "ok"
        else "unavailable"
    )
    return str(cfg.get("auto_moderate", "")).format(
        group_id=turn.group_id,
        bot_role=turn.bot_role,
        role_policy=policy_text,
        member_id=turn.member_id,
        sender_role=turn.sender_role,
        recent_ops=recent_ops,
        jev_summary=jev_summary,
    )


class DecisionPlanner:
    """Reusable Agent 1 controller executing moderation tools at temperature=0.0."""

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
        self._agent: Agent[TurnContext] | None = None

    def bind_client(self, client: AsyncOpenAI | None) -> None:
        self._openai_client = client
        self._agent = None

    def _get_agent(self) -> Agent[TurnContext]:
        if self._agent is None:
            self._agent = Agent[TurnContext](
                name="QQGroupDecisionPlanner",
                model=build_sdk_model(
                    self.settings, self.settings.decision_model, self._openai_client
                ),
                model_settings=ModelSettings(temperature=0.0),
                instructions=render_planner_instructions,
                tools=list(GROUP_ADMIN_TOOLS),
                input_guardrails=[injection_guardrail],
                output_type=DecisionOutcome,
            )
        return self._agent

    async def execute(self, turn: TurnContext) -> DecisionOutcome:
        """Run tool selection & execution, returning a structured DecisionOutcome."""
        if not self.settings.enabled:
            return DecisionOutcome()

        payload = {
            "mode": turn.mode,
            "group_id": turn.group_id,
            "message_id": turn.message_id,
            "member_id": turn.member_id,
            "text": turn.text,
            "recent_messages": turn.runtime.state.recent_context(turn.group_id),
        }
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                result = await Runner.run(
                    self._get_agent(),
                    json.dumps(payload, ensure_ascii=False),
                    context=turn,
                    max_turns=self.settings.max_turns,
                    run_config=RunConfig(workflow_name="qq-admin-planner"),
                )
        except InputGuardrailTripwireTriggered:
            logger.warning(f"qq_admin input guardrail blocked turn in {turn.group_id}")
            return DecisionOutcome(action_taken=bool(turn.executed_actions))
        except (TimeoutError, Exception) as exc:
            logger.warning(f"qq_admin DecisionPlanner failed: {exc}")
            return self._fallback_outcome(turn)

        final = result.final_output
        if isinstance(final, DecisionOutcome):
            return final.model_copy(
                update={
                    "action_taken": bool(turn.executed_actions) or final.action_taken,
                    "executed_actions": list(turn.executed_actions),
                }
            )
        return self._fallback_outcome(turn)

    @staticmethod
    def _fallback_outcome(turn: TurnContext) -> DecisionOutcome:
        acted = bool(turn.executed_actions)
        return DecisionOutcome(
            action_taken=acted,
            should_reply=acted,
            scenario="violation_handled" if acted else "no_action",
            target_id=turn.member_id,
            executed_actions=list(turn.executed_actions),
            summary="; ".join(turn.tool_outputs),
        )


__all__ = ["DecisionPlanner", "build_sdk_model", "render_planner_instructions"]
