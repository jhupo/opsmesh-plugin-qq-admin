"""Three-layer OpenAI Agents SDK guardrails backed by SafeguardPolicy & JevEvaluator."""

import json
import re
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    ToolGuardrailFunctionOutput,
    input_guardrail,
    output_guardrail,
    tool_input_guardrail,
)

from qq_admin.moderation import WriteAction

from .schemas import ReplySpec, TurnContext

_TOOL_ACTIONS: dict[str, WriteAction] = {
    "warn_member": "warn",
    "mute_member": "mute",
    "kick_member": "kick",
    "ban_member": "ban",
    "recall_message": "recall",
}


def _extract_text(raw_input: Any) -> str:
    if isinstance(raw_input, str):
        return raw_input
    if isinstance(raw_input, list):
        return "\n".join(
            item["content"]
            for item in raw_input
            if isinstance(item, dict) and isinstance(item.get("content"), str)
        )
    return str(raw_input)


@input_guardrail
async def injection_guardrail(
    ctx: RunContextWrapper[TurnContext],
    _agent: Agent[Any],
    raw_input: Any,
) -> GuardrailFunctionOutput:
    """Reject prompt-injection attempts via cached or live JevEvaluator check."""
    turn = ctx.context
    threshold = turn.runtime.config.jev.injection_block_threshold
    if turn.assessment is not None and turn.assessment.status == "ok":
        prob = turn.assessment.injection_probability
        return GuardrailFunctionOutput(
            output_info={"probability": prob},
            tripwire_triggered=prob >= threshold,
        )
    verdict = await turn.runtime.jev.check_injection(_extract_text(raw_input))
    return GuardrailFunctionOutput(
        output_info=verdict.model_dump(),
        tripwire_triggered=verdict.blocked,
    )


@tool_input_guardrail
async def action_guardrail(data: Any) -> ToolGuardrailFunctionOutput:
    """Enforce 8-step SafeguardPolicy + JevEvaluator action evidence check."""
    turn: TurnContext = data.context.context
    tool_name = str(data.context.tool_name or "")
    try:
        args = json.loads(data.context.tool_arguments or "{}")
    except json.JSONDecodeError:
        return ToolGuardrailFunctionOutput.reject_content("Invalid JSON arguments.")

    action = _TOOL_ACTIONS.get(tool_name)
    if action is None:
        return ToolGuardrailFunctionOutput.allow()

    target = str(args.get("member_id") or turn.member_id)
    raw_dur = args.get("duration_seconds") if action == "mute" else None
    verdict = await turn.runtime.policy.verify_action(
        turn.gateway,
        turn.group_id,
        target,
        action,
        duration=int(raw_dur) if isinstance(raw_dur, int) else None,
        require_confirm=(action == "kick"),
    )
    if not verdict.allowed:
        return ToolGuardrailFunctionOutput.reject_content(
            f"Safeguard blocked ({verdict.step}): {verdict.reason}"
        )

    if turn.mode == "auto_moderate" and turn.runtime.jev.is_active:
        evidence: dict[str, Any] = {
            "group_id": turn.group_id,
            "sender_id": turn.member_id,
            "message_text": turn.text[:2000],
            "recent_messages": turn.runtime.state.recent_context(turn.group_id),
        }
        if turn.assessment is not None:
            evidence["assessment"] = turn.assessment.model_dump()
        safety = await turn.runtime.jev.verify_action(
            proposal={"tool": tool_name, "arguments": args},
            evidence=evidence,
        )
        if safety.blocked:
            return ToolGuardrailFunctionOutput.reject_content(
                f"Jev verification rejected: {safety.reason}"
            )

    return ToolGuardrailFunctionOutput.allow()


@output_guardrail
async def reply_guardrail(
    ctx: RunContextWrapper[ReplySpec],
    _agent: Agent[Any],
    output: str,
) -> GuardrailFunctionOutput:
    """Block unexecuted action claims, false permission denials, and unsafe text."""
    spec = ctx.context
    text = str(output or "").strip()
    if not text:
        return GuardrailFunctionOutput(
            output_info={"skipped": True}, tripwire_triggered=False
        )

    rules = spec.runtime.catalog.composer
    if not spec.executed_actions:
        for pattern in rules.get("fake_claim_patterns", []):
            if re.search(str(pattern), text):
                return GuardrailFunctionOutput(
                    output_info={"reason": "fake_execution_claim"},
                    tripwire_triggered=True,
                )

    if spec.bot_role in ("owner", "admin") and spec.scenario != "permission_denied":
        deny_flags = [str(x) for x in rules.get("fake_deny_flags", [])]
        legit_flags = [str(x) for x in rules.get("legit_reason_flags", [])]
        if any(f in text for f in deny_flags) and not any(
            r in text for r in legit_flags
        ):
            return GuardrailFunctionOutput(
                output_info={"reason": "false_permission_denial"},
                tripwire_triggered=True,
            )

    safety = await spec.runtime.jev.check_reply(text)
    return GuardrailFunctionOutput(
        output_info=safety.model_dump(),
        tripwire_triggered=safety.blocked,
    )


__all__ = ["action_guardrail", "injection_guardrail", "reply_guardrail"]
