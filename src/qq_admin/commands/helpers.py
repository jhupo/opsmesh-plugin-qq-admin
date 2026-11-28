"""Shared admin check and ReplyAgent helpers for command handlers."""

from typing import Any

from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import MANAGER
from qq_admin.models import ReplySpec
from qq_admin.modules import IDENTITY, ActionOutcome
from qq_admin.prompts import CATALOG


def command_args(event: GroupMessageEvent, prefix_words: int = 1) -> list[str]:
    """Extract whitespace-split arguments after the command prefix words."""
    text = event.get_plaintext().strip() or (event.content or "").strip()
    parts = text.split()
    return parts[prefix_words:] if len(parts) > prefix_words else []


async def compose_reply(
    gateway: Gateway,
    event: GroupMessageEvent,
    *,
    scenario: str,
    fallback: str,
    target_id: str = "",
    executed_actions: list[str] | None = None,
    facts: dict[str, Any] | None = None,
) -> str:
    if not MANAGER.reply_agent.is_ready:
        return fallback
    group_id = event.group_openid
    operator_id = event.get_user_id()
    bot_role = await IDENTITY.bot_role(gateway, group_id)
    actor_role = await IDENTITY.member_role(gateway, group_id, operator_id)
    return await MANAGER.reply_agent.execute(
        ReplySpec(
            group_id=group_id,
            bot_role=bot_role,
            scenario=scenario,
            actor_id=operator_id,
            actor_role=actor_role,
            target_id=target_id,
            executed_actions=executed_actions or [],
            facts=facts or {},
            fallback=fallback,
        )
    )


async def require_admin(
    gateway: Gateway,
    event: GroupMessageEvent,
    matcher: Matcher,
    command_name: str,
) -> None:
    """Verify the sender is a group/global admin; finish silently or with denial."""
    group_id = event.group_openid
    if await IDENTITY.is_admin(gateway, group_id, event.get_user_id()):
        return
    if IDENTITY.config(group_id).deny_response == "reply":
        reply = await compose_reply(
            gateway,
            event,
            scenario="permission_denied",
            fallback=CATALOG.format_fallback("denied"),
            facts={"command": command_name},
        )
        await matcher.finish(reply)
    await matcher.finish()


async def finish_outcome(
    gateway: Gateway,
    event: GroupMessageEvent,
    matcher: Matcher,
    outcome: ActionOutcome,
    *,
    target_id: str = "",
) -> None:
    scenario = (
        "guard_blocked"
        if outcome.blocked_by
        else ("command_executed" if outcome.succeeded else "command_failed")
    )
    reply = await compose_reply(
        gateway,
        event,
        scenario=scenario,
        fallback=outcome.message,
        target_id=target_id,
        executed_actions=[outcome.action] if outcome.succeeded else [],
        facts={
            "action": outcome.action,
            "succeeded": outcome.succeeded,
            "blocked_by": outcome.blocked_by,
            "detail": outcome.message,
        },
    )
    await matcher.finish(reply)


__all__ = ["command_args", "compose_reply", "finish_outcome", "require_admin"]
