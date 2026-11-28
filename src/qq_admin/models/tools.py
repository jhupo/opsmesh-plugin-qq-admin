"""Official QQ v2 @function_tool definitions named directly by domain intent."""

from typing import Any, Literal

from agents import RunContextWrapper, function_tool

from .guardrails import action_guardrail


def _operator_id(turn: Any) -> str:
    return turn.member_id if turn.mode == "admin_command" else "bot"


@function_tool
async def get_member(ctx: RunContextWrapper[Any], member_id: str) -> str:
    """Query a group member's role and join timestamp from Official QQ v2."""
    turn = ctx.context
    info = await turn.gateway.get_group_member(turn.group_id, member_id)
    turn.manager.safeguard.mark_member_verified(turn.group_id, member_id)
    turn.executed_actions.append("get_member")
    summary = (
        f"member_id={info.member_openid}, role={info.member_role}, "
        f"bot={info.bot}, joined_at={info.joined_at}"
    )
    turn.tool_outputs.append(summary)
    return summary


@function_tool
async def list_muted_members(ctx: RunContextWrapper[Any]) -> str:
    """List currently muted members and global mute mode in the group."""
    turn = ctx.context
    setting = await turn.gateway.get_group_mute_setting(turn.group_id)
    turn.executed_actions.append("list_muted_members")
    entries = [
        f"{m.member_openid}(until={m.mute_expire_at})" for m in setting.members[:20]
    ]
    summary = f"global_mode={setting.global_rule.mode}, muted={entries}"
    turn.tool_outputs.append(summary)
    return summary


@function_tool(tool_input_guardrails=[action_guardrail])
async def warn_member(
    ctx: RunContextWrapper[Any],
    member_id: str,
    category: Literal["spam", "abuse", "ad"],
    reason: str,
) -> str:
    """Record a formal warning against a violating group member."""
    turn = ctx.context
    res = await turn.manager.moderation.warn(
        turn.gateway,
        turn.group_id,
        member_id,
        category=category,
        reason=reason,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("warn")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool(tool_input_guardrails=[action_guardrail])
async def mute_member(
    ctx: RunContextWrapper[Any],
    member_id: str,
    duration_seconds: int,
    reason: str,
) -> str:
    """Mute a group member for duration_seconds (1..2592000)."""
    turn = ctx.context
    res = await turn.manager.moderation.mute(
        turn.gateway,
        turn.group_id,
        member_id,
        duration=duration_seconds,
        reason=reason,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("mute")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool
async def unmute_member(ctx: RunContextWrapper[Any], member_id: str) -> str:
    """Lift a group member's mute immediately."""
    turn = ctx.context
    res = await turn.manager.moderation.unmute(
        turn.gateway,
        turn.group_id,
        member_id,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("unmute")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool(tool_input_guardrails=[action_guardrail])
async def kick_member(
    ctx: RunContextWrapper[Any],
    member_id: str,
    reason: str,
    blacklist: bool = False,
) -> str:
    """Remove a member from the group (call get_member first to verify role)."""
    turn = ctx.context
    res = await turn.manager.moderation.kick(
        turn.gateway,
        turn.group_id,
        member_id,
        reason=reason,
        blacklist=blacklist,
        operator_id=_operator_id(turn),
        require_confirm=True,
    )
    if res.succeeded:
        turn.executed_actions.append("kick")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool(tool_input_guardrails=[action_guardrail])
async def ban_member(
    ctx: RunContextWrapper[Any],
    member_id: str,
    reason: str,
) -> str:
    """Add a member to the Official QQ v2 group blacklist."""
    turn = ctx.context
    res = await turn.manager.moderation.ban(
        turn.gateway,
        turn.group_id,
        member_id,
        reason=reason,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("ban")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool
async def unban_member(ctx: RunContextWrapper[Any], member_id: str) -> str:
    """Remove a member from the Official QQ v2 group blacklist."""
    turn = ctx.context
    res = await turn.manager.moderation.unban(
        turn.gateway,
        turn.group_id,
        member_id,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("unban")
    turn.tool_outputs.append(res.message)
    return res.message


@function_tool(tool_input_guardrails=[action_guardrail])
async def recall_message(
    ctx: RunContextWrapper[Any],
    message_id: str,
    reason: str,
) -> str:
    """Recall a violating group message by its message_id."""
    turn = ctx.context
    res = await turn.manager.moderation.recall(
        turn.gateway,
        turn.group_id,
        message_id,
        target_id=turn.member_id,
        reason=reason,
        operator_id=_operator_id(turn),
    )
    if res.succeeded:
        turn.executed_actions.append("recall")
    turn.tool_outputs.append(res.message)
    return res.message


GROUP_ADMIN_TOOLS = [
    get_member,
    list_muted_members,
    warn_member,
    mute_member,
    unmute_member,
    kick_member,
    ban_member,
    unban_member,
    recall_message,
]

__all__ = [
    "GROUP_ADMIN_TOOLS",
    "ban_member",
    "get_member",
    "kick_member",
    "list_muted_members",
    "mute_member",
    "recall_message",
    "unban_member",
    "unmute_member",
    "warn_member",
]
