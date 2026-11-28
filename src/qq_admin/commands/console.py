"""/admin console commands (status, on, off, log, perm, exempt, unexempt, undo)."""

from qq_admin.moderation import ActionOutcome

from .registry import CommandContext, command


@command(
    "status",
    prefix=r"/admin\s+status",
    pattern=r"^/admin\s+status$",
    role="owner",
    usage="/admin status",
)
async def status(ctx: CommandContext) -> str:
    """Display bot role, active switch, and today's quota usage."""
    gid = ctx.group_id
    rt = ctx.runtime
    bot_role = await rt.policy.bot_role(ctx.gateway, gid)
    sf, ap = rt.config.safeguard, rt.config.approval
    unlimited = bot_role == "owner"
    return rt.catalog.format_fallback(
        "admin_status",
        group_id=gid,
        bot_role=bot_role,
        status="ON" if rt.policy.is_group_active(gid) else "PAUSED",
        mute_count=rt.state.daily_count(gid, "mute"),
        mute_limit="unlimited" if unlimited else str(sf.daily_mute_limit),
        kick_count=rt.state.daily_count(gid, "kick"),
        kick_limit="unlimited" if unlimited else str(sf.daily_kick_limit),
        approve_count=rt.state.daily_count(gid, "approve"),
        approve_limit="unlimited" if unlimited else str(ap.daily_approve_limit),
        reject_count=rt.state.daily_count(gid, "reject"),
        reject_limit="unlimited" if unlimited else str(ap.daily_reject_limit),
    )


@command(
    "on",
    prefix=r"/admin\s+on",
    pattern=r"^/admin\s+on$",
    role="owner",
    usage="/admin on",
)
async def enable(ctx: CommandContext) -> str:
    """Resume automatic moderation in the current group."""
    gid = ctx.group_id
    ctx.runtime.state.paused_groups.discard(gid)
    groups = ctx.runtime.config.moderation.enabled_groups
    if groups and gid not in groups:
        groups.append(gid)
    fallback = ctx.runtime.catalog.format_fallback("admin_on", group_id=gid)
    return await ctx.compose_reply(
        scenario="admin_toggle", fallback=fallback, facts={"enabled": True}
    )


@command(
    "off",
    prefix=r"/admin\s+off",
    pattern=r"^/admin\s+off$",
    role="owner",
    usage="/admin off",
)
async def disable(ctx: CommandContext) -> str:
    """Pause automatic moderation in the current group."""
    gid = ctx.group_id
    ctx.runtime.state.paused_groups.add(gid)
    fallback = ctx.runtime.catalog.format_fallback("admin_off", group_id=gid)
    return await ctx.compose_reply(
        scenario="admin_toggle", fallback=fallback, facts={"enabled": False}
    )


@command(
    "log",
    prefix=r"/admin\s+log",
    pattern=r"^/admin\s+log(?:\s+(?P<limit>\d+))?$",
    role="owner",
    usage="/admin log [count]",
)
async def logs(ctx: CommandContext, limit: str = "") -> str:
    """Show recent moderation audit entries for the current group."""
    gid = ctx.group_id
    rt = ctx.runtime
    count = int(limit) if limit.isdigit() else rt.config.logging.default_log_lines
    entries = rt.state.recent_audits(gid, count)
    if not entries:
        return rt.catalog.format_fallback("log_empty", group_id=gid)

    header = rt.catalog.format_fallback("log_header", group_id=gid, count=len(entries))
    lines = [header]
    for item in entries:
        mark = "OK" if item.succeeded else "ERR"
        ts = item.timestamp.strftime("%m-%d %H:%M")
        lines.append(
            f"[{ts}] {mark} {item.action} target={item.target_id} "
            f"by={item.operator_id} ({item.reason})"
        )
    return "\n".join(lines)


@command(
    "perm",
    prefix=r"/admin\s+(?:perm|perms)",
    pattern=r"^/admin\s+(?:perm|perms)(?:\s+@?(?P<member>\S+))?$",
    role="owner",
    usage="/admin perm [member_openid]",
)
async def permissions(ctx: CommandContext, member: str = "") -> str:
    """Render the full authorization and protection decision chain."""
    gid = ctx.group_id
    rt = ctx.runtime
    target = member or ctx.operator_id
    _, trace = await rt.policy.authorize(
        ctx.gateway, gid, target, minimum_role="owner", force=True
    )
    bot_role = await rt.policy.bot_role(ctx.gateway, gid, force=True)
    trace.record("bot_role", bot_role in ("owner", "admin"), f"bot_role={bot_role}")
    in_prot = target in rt.config.safeguard.protected_users
    in_ex = target in rt.state.exempt_members.get(gid, set())
    trace.record(
        "target_protected",
        in_prot or in_ex,
        f"protected={in_prot}, exempt={in_ex}",
    )
    return trace.format_text()


@command(
    "exempt",
    prefix=r"/admin\s+exempt",
    pattern=r"^/admin\s+exempt\s+@?(?P<member>\S+)$",
    role="owner",
    usage="/admin exempt <member_openid>",
)
async def exempt(ctx: CommandContext, member: str) -> str:
    """Add a member to the current group's safeguard exemption set."""
    ctx.runtime.state.exempt_members.setdefault(ctx.group_id, set()).add(member)
    return ctx.runtime.catalog.format_fallback("exempt_added", member_id=member)


@command(
    "unexempt",
    prefix=r"/admin\s+unexempt",
    pattern=r"^/admin\s+unexempt\s+@?(?P<member>\S+)$",
    role="owner",
    usage="/admin unexempt <member_openid>",
)
async def unexempt(ctx: CommandContext, member: str) -> str:
    """Remove a member from the current group's safeguard exemption set."""
    ctx.runtime.state.exempt_members.get(ctx.group_id, set()).discard(member)
    return ctx.runtime.catalog.format_fallback("exempt_removed", member_id=member)


@command(
    "undo",
    prefix=r"/admin\s+undo",
    pattern=r"^/admin\s+undo\s+@?(?P<member>\S+)$",
    role="owner",
    usage="/admin undo <member_openid>",
)
async def undo(ctx: CommandContext, member: str) -> ActionOutcome:
    """Force-unmute a member and remove any group exemption."""
    ctx.runtime.state.exempt_members.get(ctx.group_id, set()).discard(member)
    return await ctx.runtime.moderator.unmute(
        ctx.gateway, ctx.group_id, member, operator_id=ctx.operator_id
    )


__all__ = [
    "disable",
    "enable",
    "exempt",
    "logs",
    "permissions",
    "status",
    "undo",
    "unexempt",
]
