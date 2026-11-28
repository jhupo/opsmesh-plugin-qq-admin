"""Direct OpsMesh /admin console commands (deterministic, multi-group safe)."""

import json

from opsmesh import on_command
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.exception import ConfigError
from qq_admin.manager import MANAGER
from qq_admin.modules import (
    APPROVAL,
    AUDIT,
    IDENTITY,
    MODERATION,
    SAFEGUARD,
    get_module,
)
from qq_admin.prompts import notice

from .helpers import command_args, finish_outcome, require_admin

admin_status_cmd = on_command("admin status", aliases={"admin"}, priority=1, block=True)
admin_groups_cmd = on_command("admin groups", priority=1, block=True)
admin_on_cmd = on_command("admin on", priority=1, block=True)
admin_off_cmd = on_command("admin off", priority=1, block=True)
admin_config_cmd = on_command("admin config", priority=1, block=True)
admin_log_cmd = on_command("admin log", priority=1, block=True)
admin_perm_cmd = on_command("admin perm", priority=1, block=True)
admin_exempt_cmd = on_command("admin exempt", priority=1, block=True)
admin_unexempt_cmd = on_command("admin unexempt", priority=1, block=True)
admin_undo_cmd = on_command("admin undo", priority=1, block=True)


@admin_status_cmd.handle()
async def handle_admin_status(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    await require_admin(gateway, event, matcher, "admin status", group_id=group_id)

    bot_role = await IDENTITY.bot_role(gateway, group_id, force=True)
    enabled = MANAGER.is_group_enabled(group_id)
    safeguard = SAFEGUARD.config(group_id)
    approval = APPROVAL.config(group_id)
    counts = SAFEGUARD.daily_counts(group_id)
    await matcher.finish(
        notice(
            "admin_status",
            group_id=group_id,
            bot_role=bot_role,
            status="on" if enabled else "off",
            mute_count=counts["mute"],
            mute_limit=safeguard.daily_mute_limit,
            kick_count=counts["kick"],
            kick_limit=safeguard.daily_kick_limit,
            approve_count=counts["approve"],
            approve_limit=approval.daily_approve_limit,
            reject_count=counts["reject"],
            reject_limit=approval.daily_reject_limit,
        )
    )


@admin_groups_cmd.handle()
async def handle_admin_groups(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin groups")
    operator_id = event.get_user_id()
    default_mode = "on" if MANAGER.config.default_group_enabled else "off"
    candidates = MANAGER.managed_groups()
    if event.group_openid and event.group_openid not in candidates:
        candidates = sorted({*candidates, event.group_openid})

    visible: list[str] = []
    if IDENTITY.is_global_admin(operator_id):
        visible = candidates
    else:
        for gid in candidates:
            if await IDENTITY.is_admin(gateway, gid, operator_id):
                visible.append(gid)

    if not visible:
        await matcher.finish(notice("groups_empty", default_mode=default_mode))

    header = notice("groups_header", count=len(visible), default_mode=default_mode)
    lines: list[str] = [header]
    for gid in visible:
        role = await IDENTITY.bot_role(gateway, gid)
        status = "on" if MANAGER.is_group_enabled(gid) else "off"
        counts = SAFEGUARD.daily_counts(gid)
        sg = SAFEGUARD.config(gid)
        lines.append(
            f"- {gid}: status={status} bot_role={role} "
            f"mute={counts['mute']}/{sg.daily_mute_limit} "
            f"kick={counts['kick']}/{sg.daily_kick_limit}"
        )
    await matcher.finish("\n".join(lines))


@admin_on_cmd.handle()
async def handle_admin_on(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    await require_admin(gateway, event, matcher, "admin on", group_id=group_id)
    MANAGER.set_group_enabled(group_id, True)
    await matcher.finish(notice("admin_on", group_id=group_id))


@admin_off_cmd.handle()
async def handle_admin_off(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    await require_admin(gateway, event, matcher, "admin off", group_id=group_id)
    MANAGER.set_group_enabled(group_id, False)
    await matcher.finish(notice("admin_off", group_id=group_id))


@admin_config_cmd.handle()
async def handle_admin_config(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin config")
    args = command_args(event, prefix_words=2)
    group_id = event.group_openid
    try:
        if len(args) >= 2 and args[0] == "get":
            mod_name, _, field_name = args[1].partition(".")
            values = get_module(mod_name).config(group_id).model_dump()
            if not field_name:
                await matcher.finish(json.dumps(values, ensure_ascii=False))
            if field_name not in values:
                raise ConfigError(f"Unknown field: {args[1]}")
            val_json = json.dumps(values[field_name], ensure_ascii=False)
            await matcher.finish(f"{args[1]} = {val_json}")

        if len(args) >= 3 and args[0] == "set":
            mod_name, _, field_name = args[1].partition(".")
            if not field_name:
                raise ConfigError("Expected <module>.<field>")
            raw_val = " ".join(args[2:])
            updated = get_module(mod_name).update_config(group_id, field_name, raw_val)
            await matcher.finish(
                notice(
                    "config_updated",
                    group_id=group_id,
                    target=args[1],
                    value=getattr(updated, field_name),
                )
            )

        if len(args) >= 2 and args[0] == "reset":
            mod_name, _, field_name = args[1].partition(".")
            get_module(mod_name).reset_config(group_id, field_name or None)
            await matcher.finish(
                notice("config_reset", group_id=group_id, target=args[1])
            )
    except (ConfigError, ValueError) as exc:
        await matcher.finish(f"Config error: {exc}")

    await matcher.finish(
        "Usage: /admin config <get|set|reset> <module>[.<field>] [value]"
    )


@admin_log_cmd.handle()
async def handle_admin_log(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin log")
    args = command_args(event, prefix_words=2)
    group_id = event.group_openid
    limit = int(args[0]) if args and args[0].isdigit() else None
    records = AUDIT.recent_logs(group_id, limit=limit)
    if not records:
        await matcher.finish(notice("log_empty", group_id=group_id))
    header = notice("log_header", group_id=group_id, count=len(records))
    lines = [
        f"- [{r.action}] {r.target_id} by {r.operator_id} ok={r.succeeded} ({r.reason})"
        for r in records
    ]
    await matcher.finish("\n".join([header, *lines]))


@admin_perm_cmd.handle()
async def handle_admin_perm(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin perm")
    args = command_args(event, prefix_words=2)
    member_id = args[0].lstrip("@") if args else event.get_user_id()
    trace = await IDENTITY.permission_trace(
        gateway, event.group_openid, member_id, force=True
    )
    await matcher.finish(
        f"member={trace.member_id} role={trace.member_role} "
        f"bot_role={trace.bot_role} admin={trace.is_admin} ({trace.reason})"
    )


@admin_exempt_cmd.handle()
async def handle_admin_exempt(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin exempt")
    args = command_args(event, prefix_words=2)
    if not args:
        await matcher.finish("Usage: /admin exempt <member>")
    member_id = args[0].lstrip("@")
    group_id = event.group_openid
    SAFEGUARD.add_exempt(group_id, member_id)
    await matcher.finish(notice("exempt_added", group_id=group_id, member_id=member_id))


@admin_unexempt_cmd.handle()
async def handle_admin_unexempt(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin unexempt")
    args = command_args(event, prefix_words=2)
    if not args:
        await matcher.finish("Usage: /admin unexempt <member>")
    member_id = args[0].lstrip("@")
    group_id = event.group_openid
    SAFEGUARD.remove_exempt(group_id, member_id)
    await matcher.finish(
        notice("exempt_removed", group_id=group_id, member_id=member_id)
    )


@admin_undo_cmd.handle()
async def handle_admin_undo(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin undo")
    args = command_args(event, prefix_words=2)
    if not args:
        await matcher.finish("Usage: /admin undo <member>")
    member_id = args[0].lstrip("@")
    outcome = await MODERATION.undo(
        gateway, event.group_openid, member_id, operator_id=event.get_user_id()
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member_id)
