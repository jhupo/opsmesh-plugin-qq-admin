"""Shared authorization and ReplyAgent formatting helpers for command modules."""

from typing import Any

from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import ServiceManager
from qq_admin.models import ReplySpec
from qq_admin.modules import ActionOutcome, MinimumRole


def event_text(event: GroupMessageEvent) -> str:
    return event.get_plaintext().strip() or (event.content or "").strip()


async def compose_reply(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    scenario: str,
    fallback: str,
    target_id: str = "",
    executed_actions: list[str] | None = None,
    facts: dict[str, Any] | None = None,
) -> str:
    if not manager.reply_agent.is_ready:
        return fallback
    group_id = event.group_openid
    operator_id = event.get_user_id()
    bot_role = await manager.identity.bot_role(gateway, group_id)
    actor_role = await manager.identity.member_role(gateway, group_id, operator_id)
    return await manager.reply_agent.execute(
        ReplySpec(
            manager=manager,
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


async def check_access(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    minimum_role: MinimumRole,
    command_name: str,
) -> tuple[bool, str | None]:
    """Check command authorization; returns (allowed, optional_deny_reply)."""
    group_id = event.group_openid
    operator_id = event.get_user_id()
    allowed, trace = await manager.identity.authorize(
        gateway,
        group_id,
        operator_id,
        minimum_role=minimum_role,
        command=command_name,
    )
    if allowed:
        return True, None
    if manager.identity.config(group_id).deny_response != "reply":
        return False, None
    reply = await compose_reply(
        gateway,
        event,
        manager,
        scenario="permission_denied",
        fallback=manager.catalog.format_fallback("denied"),
        facts={"command": command_name, "reason": trace.reason},
    )
    return False, reply


async def render_outcome(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    outcome: ActionOutcome,
    *,
    target_id: str = "",
) -> str:
    scenario = (
        "guard_blocked"
        if outcome.blocked_by
        else ("command_executed" if outcome.succeeded else "command_failed")
    )
    return await compose_reply(
        gateway,
        event,
        manager,
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


async def finish_reply(matcher: Matcher, reply: str | None) -> None:
    if reply:
        await matcher.finish(reply)
    await matcher.finish()


__all__ = [
    "check_access",
    "compose_reply",
    "event_text",
    "finish_reply",
    "render_outcome",
]
