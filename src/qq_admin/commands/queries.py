"""Read-only inspection commands (shutlist, blacklist, requests, member)."""

from .registry import CommandContext, command


@command(
    "shutlist",
    prefix="/shutlist",
    pattern=r"^/shutlist$",
    role="admin",
    usage="/shutlist",
)
async def muted_list(ctx: CommandContext) -> str:
    """Show currently muted group members and global mute mode."""
    setting = await ctx.gateway.get_group_mute_setting(ctx.group_id)
    if not setting.members:
        return ctx.runtime.catalog.format_fallback(
            "shutlist_empty", mode=setting.global_rule.mode
        )
    lines = [f"Muted ({len(setting.members)}, global={setting.global_rule.mode}):"]
    for item in setting.members[:25]:
        lines.append(f"- {item.member_openid} until {item.mute_expire_at}")
    return "\n".join(lines)


@command(
    "blacklist",
    prefix="/blacklist",
    pattern=r"^/blacklist$",
    role="admin",
    usage="/blacklist",
)
async def blacklist(ctx: CommandContext) -> str:
    """Show members currently on the Official QQ v2 group blacklist."""
    res = await ctx.gateway.get_group_member_blacklist(ctx.group_id)
    if not res.users:
        return ctx.runtime.catalog.format_fallback("blacklist_empty")
    lines = [f"Blacklist ({len(res.users)}):"]
    for user in res.users[:25]:
        lines.append(f"- {user.member_openid} banned_at={user.banned_at}")
    return "\n".join(lines)


@command(
    "requests",
    prefix="/requests",
    pattern=r"^/requests$",
    role="admin",
    usage="/requests",
)
async def join_requests(ctx: CommandContext) -> str:
    """List pending Official QQ v2 group join requests."""
    res = await ctx.gateway.get_group_join_request_list(ctx.group_id)
    if not res.list:
        return ctx.runtime.catalog.format_fallback("requests_empty")
    lines = [f"Pending join requests ({len(res.list)}):"]
    for req in res.list[:20]:
        risk = f" risk={req.risk_tips}" if req.risk_tips else ""
        lines.append(f"- id={req.join_request_id} member={req.member_openid}{risk}")
    return "\n".join(lines)


@command(
    "member",
    prefix="/member",
    pattern=r"^/member(?:\s+@?(?P<member>\S+))?$",
    role="admin",
    usage="/member [member_openid]",
)
async def member_profile(ctx: CommandContext, member: str = "") -> str:
    """Inspect a group member's role and join timestamp."""
    target = member or ctx.operator_id
    role = await ctx.runtime.policy.member_role(
        ctx.gateway, ctx.group_id, target, force=True
    )
    info = await ctx.gateway.get_group_member(ctx.group_id, target)
    ctx.runtime.state.mark_member_verified(ctx.group_id, target)
    return (
        f"member={info.member_openid}\n"
        f"role={role}\n"
        f"bot={info.bot}\n"
        f"joined_at={info.joined_at}"
    )


__all__ = ["blacklist", "join_requests", "member_profile", "muted_list"]
