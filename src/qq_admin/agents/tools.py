"""Atomic Official QQ v2 @function_tool set bound to DecisionAgent."""

from typing import Literal

from agents import RunContextWrapper, function_tool

from qq_admin.moderation import (
    ban_member,
    kick_member,
    mute_member,
    recall_message,
    unban_member,
    unmute_member,
    warn_member,
)

from .context import ModerationContext
from .guardrails import moderation_tool_guardrail


@function_tool(name_override="group_get_member")
async def tool_get_member(
    ctx: RunContextWrapper[ModerationContext], member_openid: str
) -> str:
    """Query a group member's role and join time from Official QQ v2."""
    mctx = ctx.context
    info = await mctx.gateway.get_group_member(mctx.group_openid, member_openid)
    mctx.runtime.state.mark_member_checked(mctx.group_openid, member_openid)
    mctx.executed_actions.append("get_member")
    summary = (
        f"member_openid={info.member_openid}, role={info.member_role}, "
        f"bot={info.bot}, joined_at={info.joined_at}"
    )
    mctx.tool_results.append(summary)
    return summary


@function_tool(name_override="group_list_muted")
async def tool_list_muted(ctx: RunContextWrapper[ModerationContext]) -> str:
    """List currently muted members and global mute mode in the group."""
    mctx = ctx.context
    setting = await mctx.gateway.get_group_mute_setting(mctx.group_openid)
    mctx.executed_actions.append("list_muted")
    members = [
        f"{m.member_openid}(until={m.mute_expire_at})" for m in setting.members[:20]
    ]
    summary = f"global_mode={setting.global_rule.mode}, muted={members}"
    mctx.tool_results.append(summary)
    return summary


@function_tool(
    name_override="group_warn_member",
    tool_input_guardrails=[moderation_tool_guardrail],
)
async def tool_warn_member(
    ctx: RunContextWrapper[ModerationContext],
    member_openid: str,
    category: Literal["spam", "abuse", "ad"],
    reason: str,
) -> str:
    """Record a formal warning against a violating member."""
    mctx = ctx.context
    res = await warn_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        category=category,
        reason=reason,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("warn")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(
    name_override="group_mute_member",
    tool_input_guardrails=[moderation_tool_guardrail],
)
async def tool_mute_member(
    ctx: RunContextWrapper[ModerationContext],
    member_openid: str,
    duration_seconds: int,
    reason: str,
) -> str:
    """Mute a group member for duration_seconds (1..2592000)."""
    mctx = ctx.context
    res = await mute_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        duration=duration_seconds,
        reason=reason,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("mute")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(name_override="group_unmute_member")
async def tool_unmute_member(
    ctx: RunContextWrapper[ModerationContext], member_openid: str
) -> str:
    """Unmute a group member immediately."""
    mctx = ctx.context
    res = await unmute_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("unmute")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(
    name_override="group_kick_member",
    tool_input_guardrails=[moderation_tool_guardrail],
)
async def tool_kick_member(
    ctx: RunContextWrapper[ModerationContext],
    member_openid: str,
    reason: str,
    add_to_blacklist: bool = False,
) -> str:
    """Remove a member from the group (call group_get_member first)."""
    mctx = ctx.context
    res = await kick_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        reason=reason,
        add_to_blacklist=add_to_blacklist,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
        require_member_check=True,
    )
    if res.ok:
        mctx.executed_actions.append("kick")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(
    name_override="group_ban_member",
    tool_input_guardrails=[moderation_tool_guardrail],
)
async def tool_ban_member(
    ctx: RunContextWrapper[ModerationContext],
    member_openid: str,
    reason: str,
) -> str:
    """Add a member to the group blacklist."""
    mctx = ctx.context
    res = await ban_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        reason=reason,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("ban")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(name_override="group_unban_member")
async def tool_unban_member(
    ctx: RunContextWrapper[ModerationContext], member_openid: str
) -> str:
    """Remove a member from the group blacklist."""
    mctx = ctx.context
    res = await unban_member(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        member_openid=member_openid,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("unban")
    mctx.tool_results.append(res.summary)
    return res.summary


@function_tool(
    name_override="group_recall_message",
    tool_input_guardrails=[moderation_tool_guardrail],
)
async def tool_recall_message(
    ctx: RunContextWrapper[ModerationContext],
    message_id: str,
    reason: str,
) -> str:
    """Recall a violating group message by message_id."""
    mctx = ctx.context
    res = await recall_message(
        mctx.gateway,
        mctx.runtime,
        group_openid=mctx.group_openid,
        message_id=message_id,
        target_openid=mctx.member_openid,
        reason=reason,
        operator_openid=mctx.member_openid if mctx.mode == "admin_command" else "bot",
    )
    if res.ok:
        mctx.executed_actions.append("recall")
    mctx.tool_results.append(res.summary)
    return res.summary


MODERATION_TOOLS = [
    tool_get_member,
    tool_list_muted,
    tool_warn_member,
    tool_mute_member,
    tool_unmute_member,
    tool_kick_member,
    tool_ban_member,
    tool_unban_member,
    tool_recall_message,
]

__all__ = ["MODERATION_TOOLS"]
