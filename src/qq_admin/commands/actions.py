"""Moderation write commands (warn, mute, unmute, kick, ban, unban, recall, join)."""

from typing import Literal, cast

from qq_admin.moderation import ActionOutcome

from .registry import CommandContext, command


@command(
    "warn",
    prefix="/warn",
    pattern=r"^/warn\s+@?(?P<member>\S+)\s+(?P<category>spam|abuse|ad)(?:\s+(?P<reason>.+))?$",
    role="admin",
    usage="/warn <member_openid> <spam|abuse|ad> [reason]",
)
async def warn(
    ctx: CommandContext, member: str, category: str, reason: str = ""
) -> ActionOutcome:
    """Issue a formal windowed warning to a group member."""
    cat = cast(Literal["spam", "abuse", "ad"], category.lower())
    return await ctx.runtime.moderator.warn(
        ctx.gateway,
        ctx.group_id,
        member,
        category=cat,
        reason=reason or "manual warning",
        operator_id=ctx.operator_id,
    )


@command(
    "mute",
    prefix="/mute",
    pattern=r"^/mute\s+@?(?P<member>\S+)\s+(?P<duration>\S+)(?:\s+(?P<reason>.+))?$",
    role="admin",
    usage="/mute <member_openid> <10m|1h|600> [reason]",
)
async def mute(
    ctx: CommandContext, member: str, duration: str, reason: str = ""
) -> ActionOutcome:
    """Mute a group member for the requested duration."""
    return await ctx.runtime.moderator.mute(
        ctx.gateway,
        ctx.group_id,
        member,
        duration=duration,
        reason=reason or "manual mute",
        operator_id=ctx.operator_id,
    )


@command(
    "unmute",
    prefix="/unmute",
    pattern=r"^/unmute\s+@?(?P<member>\S+)$",
    role="admin",
    usage="/unmute <member_openid>",
)
async def unmute(ctx: CommandContext, member: str) -> ActionOutcome:
    """Lift a group member's mute immediately."""
    return await ctx.runtime.moderator.unmute(
        ctx.gateway, ctx.group_id, member, operator_id=ctx.operator_id
    )


@command(
    "kick",
    prefix="/kick",
    pattern=r"^/kick\s+@?(?P<member>\S+)(?P<flag>\s+--ban)?(?:\s+(?P<reason>.+))?$",
    role="admin",
    usage="/kick <member_openid> [--ban] [reason]",
)
async def kick(
    ctx: CommandContext, member: str, flag: str = "", reason: str = ""
) -> ActionOutcome:
    """Remove a member from the group, optionally adding them to the blacklist."""
    return await ctx.runtime.moderator.kick(
        ctx.gateway,
        ctx.group_id,
        member,
        reason=reason or "manual kick",
        blacklist=bool(flag),
        operator_id=ctx.operator_id,
    )


@command(
    "ban",
    prefix="/ban",
    pattern=r"^/ban\s+@?(?P<member>\S+)(?:\s+(?P<reason>.+))?$",
    role="admin",
    usage="/ban <member_openid> [reason]",
)
async def ban(ctx: CommandContext, member: str, reason: str = "") -> ActionOutcome:
    """Add a member to the Official QQ v2 group blacklist."""
    return await ctx.runtime.moderator.ban(
        ctx.gateway,
        ctx.group_id,
        member,
        reason=reason or "manual blacklist",
        operator_id=ctx.operator_id,
    )


@command(
    "unban",
    prefix="/unban",
    pattern=r"^/unban\s+@?(?P<member>\S+)$",
    role="admin",
    usage="/unban <member_openid>",
)
async def unban(ctx: CommandContext, member: str) -> ActionOutcome:
    """Remove a member from the Official QQ v2 group blacklist."""
    return await ctx.runtime.moderator.unban(
        ctx.gateway, ctx.group_id, member, operator_id=ctx.operator_id
    )


@command(
    "recall",
    prefix="/recall",
    pattern=r"^/recall\s+(?P<message_id>\S+)$",
    role="admin",
    usage="/recall <message_id>",
)
async def recall(ctx: CommandContext, message_id: str) -> ActionOutcome:
    """Recall a group message by message_id."""
    return await ctx.runtime.moderator.recall(
        ctx.gateway,
        ctx.group_id,
        message_id,
        operator_id=ctx.operator_id,
    )


@command(
    "approve",
    prefix="/approve",
    pattern=r"^/approve\s+@?(?P<member>\S+)\s+(?P<request_id>\S+)$",
    role="admin",
    usage="/approve <member_openid> <join_request_id>",
)
async def approve(ctx: CommandContext, member: str, request_id: str) -> ActionOutcome:
    """Approve a pending group join request."""
    return await ctx.runtime.approver.approve(
        ctx.gateway,
        ctx.group_id,
        member,
        request_id,
        operator_id=ctx.operator_id,
    )


@command(
    "reject",
    prefix="/reject",
    pattern=r"^/reject\s+@?(?P<member>\S+)\s+(?P<request_id>\S+)(?:\s+(?P<reason>.+))?$",
    role="admin",
    usage="/reject <member_openid> <join_request_id> [reason]",
)
async def reject(
    ctx: CommandContext, member: str, request_id: str, reason: str = ""
) -> ActionOutcome:
    """Reject a pending group join request."""
    return await ctx.runtime.approver.reject(
        ctx.gateway,
        ctx.group_id,
        member,
        request_id,
        reason=reason or "rejected by admin",
        operator_id=ctx.operator_id,
    )


__all__ = [
    "approve",
    "ban",
    "kick",
    "mute",
    "recall",
    "reject",
    "unban",
    "unmute",
    "warn",
]
