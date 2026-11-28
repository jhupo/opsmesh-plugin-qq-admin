"""Agent 2 (ReplyAgent): generates natural, non-repetitive contextual replies."""

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
from opsmesh.log import logger

from qq_admin.state import PluginRuntime

from .context import ReplyContext
from .decision_agent import resolve_openai_model
from .guardrails import reply_output_guardrail


def build_reply_instructions(
    ctx: RunContextWrapper[ReplyContext], _agent: Agent[ReplyContext]
) -> str:
    """Inject live group state + role persona prompt so ReplyAgent phrases freely."""
    rctx = ctx.context
    cfg = rctx.runtime.config
    reply_cfg = rctx.runtime.prompts.get("reply_agent", {})
    persona = cfg.llm.reply_persona.strip() or str(reply_cfg.get("persona", "")).strip()
    tmpl = str(reply_cfg.get("instructions", ""))

    sf = cfg.safeguard
    mute_limit = "unlimited" if rctx.bot_role == "owner" else str(sf.daily_mute_limit)
    kick_limit = "unlimited" if rctx.bot_role == "owner" else str(sf.daily_kick_limit)

    return tmpl.format(
        persona=persona,
        group_openid=rctx.group_openid,
        bot_role=rctx.bot_role,
        scenario=rctx.scenario,
        actor_openid=rctx.actor_openid,
        actor_role=rctx.actor_role,
        target_openid=rctx.target_openid or "-",
        mute_count=rctx.runtime.state.get_daily_count(rctx.group_openid, "mute"),
        mute_limit=mute_limit,
        kick_count=rctx.runtime.state.get_daily_count(rctx.group_openid, "kick"),
        kick_limit=kick_limit,
    )


def build_reply_agent(runtime: PluginRuntime) -> Agent[ReplyContext]:
    """Construct ReplyAgent (no write tools, higher temperature, output guardrail)."""
    llm = runtime.config.llm
    return Agent[ReplyContext](
        name="QQGroupReplyAgent",
        model=resolve_openai_model(llm, llm.effective_reply_model),
        model_settings=ModelSettings(temperature=llm.reply_temperature),
        instructions=build_reply_instructions,
        tools=[],
        output_guardrails=[reply_output_guardrail],
    )


async def generate_reply(
    rctx: ReplyContext,
    *,
    agent: Agent[ReplyContext] | None = None,
) -> str:
    """Generate a natural contextual moderation reply or fall back cleanly."""
    llm = rctx.runtime.config.llm
    if not llm.enabled:
        return rctx.fallback_text

    composer = agent or build_reply_agent(rctx.runtime)
    payload = {
        "scenario": rctx.scenario,
        "group_openid": rctx.group_openid,
        "bot_role": rctx.bot_role,
        "actor_openid": rctx.actor_openid,
        "actor_role": rctx.actor_role,
        "target_openid": rctx.target_openid,
        "executed_actions": rctx.executed_actions,
        "facts": rctx.facts,
    }
    try:
        async with asyncio.timeout(llm.timeout_seconds):
            result = await Runner.run(
                composer,
                json.dumps(payload, ensure_ascii=False),
                context=rctx,
                max_turns=2,
                run_config=RunConfig(workflow_name="opsmesh-qq-admin-reply"),
            )
    except OutputGuardrailTripwireTriggered:
        logger.warning(
            f"qq_admin reply guardrail blocked output in {rctx.group_openid}"
        )
        return rctx.fallback_text
    except (TimeoutError, Exception) as exc:
        logger.warning(f"qq_admin reply agent failed (using fallback): {exc}")
        return rctx.fallback_text

    text = str(result.final_output or "").strip()
    return text or rctx.fallback_text


__all__ = [
    "build_reply_agent",
    "build_reply_instructions",
    "generate_reply",
]
