"""Jev-backed OpenAI Agents SDK input, tool-input, and output guardrails."""

import json
import re
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    input_guardrail,
    output_guardrail,
    tool_input_guardrail,
)


def _as_text(payload: Any) -> str:
    if isinstance(payload, list):
        return "\n".join(str(item) for item in payload)
    return str(payload)


def _claims_unexecuted_action(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _denies_real_permission(
    text: str, *, bot_role: str, deny_flags: list[str], legit_flags: list[str]
) -> bool:
    if bot_role not in {"owner", "admin"}:
        return False
    if not any(flag in text for flag in deny_flags):
        return False
    return not any(flag in text for flag in legit_flags)


def _pass(**info: Any) -> GuardrailFunctionOutput:
    return GuardrailFunctionOutput(output_info=info, tripwire_triggered=False)


def _trip(**info: Any) -> GuardrailFunctionOutput:
    return GuardrailFunctionOutput(output_info=info, tripwire_triggered=True)


@input_guardrail
async def injection_guardrail(
    ctx: RunContextWrapper[Any], agent: Agent[Any], user_input: str | list[Any]
) -> GuardrailFunctionOutput:
    """Block prompt-injection or privilege-spoofing attempts before a turn."""
    del agent
    turn = ctx.context
    manager = turn.manager
    if turn.mode == "admin_command" or not manager.jev.is_ready:
        return _pass(skipped=True)
    prob = await manager.jev.probability(
        {"input": _as_text(user_input)[:2000]},
        manager.catalog.jev_guard("input_injection"),
    )
    threshold = manager.moderation.config(turn.group_id).injection_block_threshold
    return _trip(injection=prob) if prob >= threshold else _pass(injection=prob)


@tool_input_guardrail
async def action_guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Second-check every punitive tool call against the evidence via Jev."""
    turn = data.context.context
    manager = turn.manager
    cfg = manager.moderation.config(turn.group_id)
    if (
        turn.mode == "admin_command"
        or not cfg.enable_action_guardrail
        or not manager.jev.is_ready
    ):
        return ToolGuardrailFunctionOutput.allow({"skipped": True})

    try:
        arguments = json.loads(data.context.tool_arguments or "{}")
    except json.JSONDecodeError:
        arguments = {"raw": data.context.tool_arguments}

    validity = await manager.jev.probability(
        {
            "proposal": {"tool": data.context.tool_name, "arguments": arguments},
            "evidence": {
                "member_id": turn.member_id,
                "message": turn.message_text[:2000],
                "jev": turn.jev_summary,
            },
        },
        manager.catalog.jev_guard("moderation_validity"),
    )
    if validity < cfg.action_validity_threshold:
        return ToolGuardrailFunctionOutput.reject_content(
            f"Action rejected by evidence check (validity={validity:.2f}).",
            output_info={"validity": validity},
        )
    return ToolGuardrailFunctionOutput.allow({"validity": validity})


@output_guardrail
async def reply_guardrail(
    ctx: RunContextWrapper[Any], agent: Agent[Any], agent_output: Any
) -> GuardrailFunctionOutput:
    """Block hallucinated action claims, false denials, or unsafe replies."""
    del agent
    spec = ctx.context
    manager = spec.manager
    catalog = manager.catalog
    text = str(agent_output or "").strip()
    if not text:
        return _pass(empty=True)

    if not spec.executed_actions and _claims_unexecuted_action(
        text, catalog.fake_claim_patterns()
    ):
        return _trip(reason="hallucinated_action_claim")
    if _denies_real_permission(
        text,
        bot_role=spec.bot_role,
        deny_flags=catalog.fake_deny_flags(),
        legit_flags=catalog.legit_reason_flags(),
    ):
        return _trip(reason="false_permission_denial")

    if manager.jev.is_ready:
        prob = await manager.jev.probability(
            {"output": text[:1000]}, catalog.jev_guard("output_safety")
        )
        if prob >= manager.moderation.config(spec.group_id).output_safety_threshold:
            return _trip(reason="unsafe_reply", probability=prob)
    return _pass(safe=True)


__all__ = ["action_guardrail", "injection_guardrail", "reply_guardrail"]
