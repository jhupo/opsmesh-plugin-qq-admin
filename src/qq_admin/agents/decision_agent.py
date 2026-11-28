"""Agent 1 (DecisionAgent): tool execution controller returning ExecutionReport."""

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

from qq_admin.config import LLMConfig
from qq_admin.state import PluginRuntime

from .context import ExecutionReport, ModerationContext
from .guardrails import prompt_injection_guardrail
from .tools import MODERATION_TOOLS


def resolve_openai_model(llm: LLMConfig, model_name: str) -> Any:
    """Build OpenAIChatCompletionsModel when custom key/base_url is configured."""
    if llm.use_chat_completions or llm.base_url.strip() or llm.api_key.strip():
        client = AsyncOpenAI(
            api_key=llm.api_key or None,
            base_url=llm.base_url.strip() or None,
            timeout=llm.timeout_seconds,
        )
        return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
    return model_name


def build_decision_instructions(
    ctx: RunContextWrapper[ModerationContext], _agent: Agent[ModerationContext]
) -> str:
    """Render deterministic decision instructions from external prompts.toml."""
    mctx = ctx.context
    cfg_dec = mctx.runtime.prompts.get("decision_agent", {})
    policy_key = f"role_policy_{mctx.bot_role}"
    role_policy = str(cfg_dec.get(policy_key, cfg_dec.get("role_policy_member", "")))

    if mctx.mode == "admin_command":
        tmpl = str(cfg_dec.get("admin_command_instructions", ""))
        return tmpl.format(
            group_openid=mctx.group_openid,
            bot_role=mctx.bot_role,
            role_policy=role_policy,
            member_openid=mctx.member_openid,
            sender_role=mctx.sender_role,
        )

    recent_ops = mctx.runtime.state.count_recent_ops(
        mctx.group_openid, mctx.member_openid, within_hours=24.0
    )
    jev_summary = (
        f"violation={mctx.evaluation.primary_violation}, "
        f"severity={mctx.evaluation.violation_severity:.2f}, "
        f"confidence={mctx.evaluation.effective_confidence:.2f}, "
        f"banter_prob={mctx.evaluation.is_friendly_banter_prob:.2f}"
        if mctx.evaluation and mctx.evaluation.status == "ok"
        else "unavailable"
    )
    tmpl = str(cfg_dec.get("auto_moderate_instructions", ""))
    return tmpl.format(
        group_openid=mctx.group_openid,
        bot_role=mctx.bot_role,
        role_policy=role_policy,
        member_openid=mctx.member_openid,
        sender_role=mctx.sender_role,
        recent_ops=recent_ops,
        jev_summary=jev_summary,
    )


def build_decision_agent(runtime: PluginRuntime) -> Agent[ModerationContext]:
    """Construct DecisionAgent (temperature=0.0, tools + input/tool guardrails)."""
    llm = runtime.config.llm
    return Agent[ModerationContext](
        name="QQGroupDecisionAgent",
        model=resolve_openai_model(llm, llm.decision_model),
        model_settings=ModelSettings(temperature=0.0),
        instructions=build_decision_instructions,
        tools=list(MODERATION_TOOLS),
        input_guardrails=[prompt_injection_guardrail],
        output_type=ExecutionReport,
    )


async def run_decision_agent(
    mctx: ModerationContext,
    *,
    agent: Agent[ModerationContext] | None = None,
) -> ExecutionReport:
    """Run DecisionAgent to execute tools and return structured ExecutionReport."""
    llm = mctx.runtime.config.llm
    if not llm.enabled:
        return ExecutionReport()

    controller = agent or build_decision_agent(mctx.runtime)
    recent = mctx.runtime.state.get_recent_messages(mctx.group_openid, limit=8)
    payload = {
        "mode": mctx.mode,
        "group_openid": mctx.group_openid,
        "message_id": mctx.message_id,
        "member_openid": mctx.member_openid,
        "text": mctx.plain_text,
        "recent_messages": recent,
    }
    try:
        async with asyncio.timeout(llm.timeout_seconds):
            result = await Runner.run(
                controller,
                json.dumps(payload, ensure_ascii=False),
                context=mctx,
                max_turns=llm.max_turns,
                run_config=RunConfig(workflow_name="opsmesh-qq-admin-decision"),
            )
    except InputGuardrailTripwireTriggered:
        logger.warning(f"qq_admin input guardrail blocked turn in {mctx.group_openid}")
        return ExecutionReport(
            action_taken=bool(mctx.executed_actions),
            should_reply=False,
            scenario="no_action",
        )
    except TimeoutError:
        logger.warning(
            f"qq_admin decision agent timed out after {llm.timeout_seconds}s"
        )
        return ExecutionReport(
            action_taken=bool(mctx.executed_actions),
            should_reply=bool(mctx.executed_actions),
            scenario="violation_handled" if mctx.executed_actions else "no_action",
            target_openid=mctx.member_openid,
            executed_actions=list(mctx.executed_actions),
            facts_summary="; ".join(mctx.tool_results),
        )
    except Exception as exc:
        logger.warning(f"qq_admin decision agent failed: {exc}")
        return ExecutionReport(
            action_taken=bool(mctx.executed_actions),
            should_reply=bool(mctx.executed_actions),
            scenario="violation_handled" if mctx.executed_actions else "no_action",
            target_openid=mctx.member_openid,
            executed_actions=list(mctx.executed_actions),
            facts_summary="; ".join(mctx.tool_results),
        )

    final = result.final_output
    if isinstance(final, ExecutionReport):
        return final.model_copy(
            update={
                "action_taken": bool(mctx.executed_actions) or final.action_taken,
                "executed_actions": list(mctx.executed_actions),
            }
        )
    return ExecutionReport(
        action_taken=bool(mctx.executed_actions),
        should_reply=bool(mctx.executed_actions),
        executed_actions=list(mctx.executed_actions),
        facts_summary="; ".join(mctx.tool_results),
    )


__all__ = [
    "build_decision_agent",
    "build_decision_instructions",
    "resolve_openai_model",
    "run_decision_agent",
]
