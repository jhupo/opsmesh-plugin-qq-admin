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

from qq_admin.prompts import load_toml

from .jev import ATTACK_FIELDS, CRITICAL_FIELDS

_REPLY_SAFETY_FIELDS = (*CRITICAL_FIELDS, "pii", "unethical_behavior")


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
    """Block prompt-injection/jailbreak, reusing precomputed SafetyReport if any."""
    del agent
    from qq_admin.manager import MANAGER
    from qq_admin.modules.moderation import MODERATION

    turn = ctx.context
    if turn.mode == "admin_command":
        return _pass(skipped=True)

    threshold = MODERATION.config(turn.group_id).attack_threshold
    report = turn.report
    if report is None:
        if not MANAGER.jev.is_ready:
            return _pass(skipped=True)
        report = await MANAGER.jev.execute(
            text=_as_text(user_input)[:2000],
            categories=ATTACK_FIELDS,
            include_severity=False,
        )
    risk = report.max_attack_risk
    return _trip(attack=risk) if risk >= threshold else _pass(attack=risk)


@tool_input_guardrail
async def action_guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Optional second-check verifying a punitive tool call matches the evidence."""
    from qq_admin.manager import MANAGER
    from qq_admin.modules.moderation import MODERATION

    turn = data.context.context
    cfg = MODERATION.config(turn.group_id)
    if (
        turn.mode == "admin_command"
        or not cfg.enable_action_guardrail
        or not MANAGER.jev.is_ready
    ):
        return ToolGuardrailFunctionOutput.allow({"skipped": True})

    try:
        arguments = json.loads(data.context.tool_arguments or "{}")
    except json.JSONDecodeError:
        arguments = {"raw": data.context.tool_arguments}

    instructions = str(
        load_toml("jev_guards.toml").get("guards", {}).get("moderation_validity", "")
    )
    validity = await MANAGER.jev.probability(
        {
            "proposal": {"tool": data.context.tool_name, "arguments": arguments},
            "evidence": {
                "member_id": turn.member_id,
                "jev": turn.report.summary() if turn.report else "none",
            },
        },
        instructions,
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
    """Block hallucinated action claims, false denials, or unsafe replies via Jev."""
    del agent
    from qq_admin.manager import MANAGER
    from qq_admin.modules.moderation import MODERATION

    spec = ctx.context
    text = str(agent_output or "").strip()
    if not text:
        return _pass(empty=True)

    guard_cfg = load_toml("notices.toml").get("reply_guard", {})
    if not spec.executed_actions and _claims_unexecuted_action(
        text, list(guard_cfg.get("fake_claim_patterns", []))
    ):
        return _trip(reason="hallucinated_action_claim")
    if _denies_real_permission(
        text,
        bot_role=spec.bot_role,
        deny_flags=list(guard_cfg.get("fake_deny_flags", [])),
        legit_flags=list(guard_cfg.get("legit_reason_flags", [])),
    ):
        return _trip(reason="false_permission_denial")

    if MANAGER.jev.is_ready:
        report = await MANAGER.jev.execute(
            text=text[:1000],
            categories=_REPLY_SAFETY_FIELDS,
            include_severity=False,
        )
        threshold = MODERATION.config(spec.group_id).output_safety_threshold
        if report.max_risk >= threshold:
            return _trip(reason="unsafe_reply", risk=report.max_risk)
    return _pass(safe=True)


__all__ = ["action_guardrail", "injection_guardrail", "reply_guardrail"]
