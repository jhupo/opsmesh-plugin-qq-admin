"""Pure deterministic output guardrail for ReplyAgent responses (zero network calls)."""

import re
from typing import Any

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, output_guardrail

from qq_admin.prompts import load_toml


def sanitize_reply_text(raw: str) -> str:
    """Strip surrounding code fences, quotes, and excess blank lines."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


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


@output_guardrail
async def reply_guardrail(
    ctx: RunContextWrapper[Any], agent: Agent[Any], agent_output: Any
) -> GuardrailFunctionOutput:
    """Block hallucinated action claims, false permission denials, or oversized text."""
    del agent
    spec = ctx.context
    text = sanitize_reply_text(str(agent_output or ""))
    if not text:
        return _pass(empty=True)

    guard_cfg = load_toml("notices.toml").get("reply_guard", {})
    max_chars = int(guard_cfg.get("max_reply_chars", 200))
    if len(text) > max_chars:
        return _trip(reason="reply_too_long", length=len(text))

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

    return _pass(safe=True)


__all__ = ["reply_guardrail", "sanitize_reply_text"]
