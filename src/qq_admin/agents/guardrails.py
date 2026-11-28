"""Three-layer OpenAI Agents SDK Guardrails backed by injected JevClient."""

import json
import re
from typing import Any, Literal

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    ToolGuardrailFunctionOutput,
    input_guardrail,
    output_guardrail,
    tool_input_guardrail,
)

from qq_admin.jev import (
    check_action_validity,
    check_input_injection,
    check_output_safety,
)
from qq_admin.moderation import check_action_guard

from .context import ModerationContext, ReplyContext

_WRITE_TOOL_TO_ACTION: dict[str, Literal["warn", "mute", "kick", "ban", "recall"]] = {
    "group_warn_member": "warn",
    "group_mute_member": "mute",
    "group_kick_member": "kick",
    "group_ban_member": "ban",
    "group_recall_message": "recall",
}


def _flatten_input(raw_input: Any) -> str:
    if isinstance(raw_input, str):
        return raw_input
    if isinstance(raw_input, list):
        parts: list[str] = []
        for item in raw_input:
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
        return "\n".join(parts)
    return str(raw_input)


@input_guardrail
async def prompt_injection_guardrail(
    ctx: RunContextWrapper[ModerationContext],
    _agent: Agent[Any],
    raw_input: Any,
) -> GuardrailFunctionOutput:
    """Block prompt injection using cached or live injected JevClient check."""
    mctx = ctx.context
    cfg = mctx.runtime.config.jev
    if mctx.evaluation is not None and mctx.evaluation.status == "ok":
        prob = mctx.evaluation.is_prompt_injection_prob
        return GuardrailFunctionOutput(
            output_info={"probability": prob},
            tripwire_triggered=prob >= cfg.injection_block_threshold,
        )
    verdict = await check_input_injection(
        mctx.runtime.jev_client,
        mctx.runtime.config.jev,
        mctx.runtime.prompts,
        _flatten_input(raw_input),
    )
    return GuardrailFunctionOutput(
        output_info=verdict.model_dump(),
        tripwire_triggered=verdict.blocked,
    )


@tool_input_guardrail
async def moderation_tool_guardrail(data: Any) -> ToolGuardrailFunctionOutput:
    """Enforce 8-step hard safeguard + JevClient action evidence verification."""
    mctx: ModerationContext = data.context.context
    tool_name: str = str(data.context.tool_name or "")
    try:
        args = json.loads(data.context.tool_arguments or "{}")
    except json.JSONDecodeError:
        return ToolGuardrailFunctionOutput.reject_content("Invalid JSON arguments.")

    action = _WRITE_TOOL_TO_ACTION.get(tool_name)
    if action is None:
        return ToolGuardrailFunctionOutput.allow()

    target = str(args.get("member_openid") or mctx.member_openid)
    duration = args.get("duration_seconds") if action == "mute" else None
    decision = await check_action_guard(
        mctx.gateway,
        mctx.runtime.config,
        mctx.runtime.state,
        group_openid=mctx.group_openid,
        target_openid=target,
        action=action,
        duration_seconds=int(duration) if isinstance(duration, int) else None,
        require_member_check=(action == "kick"),
    )
    if not decision.allowed:
        return ToolGuardrailFunctionOutput.reject_content(
            f"Safeguard blocked ({decision.step}): {decision.reason}"
        )

    if (
        mctx.mode == "auto_moderate"
        and mctx.runtime.jev_client is not None
        and mctx.runtime.config.jev.enabled
    ):
        evidence: dict[str, Any] = {
            "group_openid": mctx.group_openid,
            "sender_openid": mctx.member_openid,
            "message_text": mctx.plain_text[:2000],
            "recent_messages": mctx.runtime.state.get_recent_messages(
                mctx.group_openid, limit=8
            ),
        }
        if mctx.evaluation is not None:
            evidence["jev_eval"] = mctx.evaluation.model_dump()

        verdict = await check_action_validity(
            mctx.runtime.jev_client,
            mctx.runtime.config.jev,
            mctx.runtime.prompts,
            proposal={"tool": tool_name, "arguments": args},
            evidence=evidence,
        )
        if verdict.blocked:
            return ToolGuardrailFunctionOutput.reject_content(
                f"Jev verification rejected: {verdict.reason}"
            )

    return ToolGuardrailFunctionOutput.allow()


@output_guardrail
async def reply_output_guardrail(
    ctx: RunContextWrapper[ReplyContext],
    _agent: Agent[Any],
    output: str,
) -> GuardrailFunctionOutput:
    """Block fake execution claims, false denials, and unsafe replies."""
    rctx = ctx.context
    text = str(output or "").strip()
    if not text:
        return GuardrailFunctionOutput(
            output_info={"skipped": True}, tripwire_triggered=False
        )

    reply_prompts = rctx.runtime.prompts.get("reply_agent", {})
    if not rctx.executed_actions:
        for pat in reply_prompts.get("fake_claim_patterns", []):
            if re.search(str(pat), text):
                return GuardrailFunctionOutput(
                    output_info={"reason": "fake_execution_claim"},
                    tripwire_triggered=True,
                )

    if rctx.bot_role in ("owner", "admin") and rctx.scenario != "permission_denied":
        deny_flags = [str(x) for x in reply_prompts.get("fake_deny_flags", [])]
        legit_flags = [str(x) for x in reply_prompts.get("legit_reason_flags", [])]
        if any(f in text for f in deny_flags) and not any(
            r in text for r in legit_flags
        ):
            return GuardrailFunctionOutput(
                output_info={"reason": "false_permission_denial"},
                tripwire_triggered=True,
            )

    verdict = await check_output_safety(
        rctx.runtime.jev_client, rctx.runtime.config.jev, rctx.runtime.prompts, text
    )
    return GuardrailFunctionOutput(
        output_info=verdict.model_dump(),
        tripwire_triggered=verdict.blocked,
    )


__all__ = [
    "moderation_tool_guardrail",
    "prompt_injection_guardrail",
    "reply_output_guardrail",
]
