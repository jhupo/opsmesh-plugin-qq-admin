"""Direct OpsMesh /admin commands for group toggles, online config, and logs."""

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
from qq_admin.prompts import CATALOG

from .helpers import command_args, compose_reply, finish_outcome, require_admin

admin_status_cmd = on_command("admin status", aliases={"admin"}, priority=1, block=True)
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
    await require_admin(gateway, event, matcher, "admin status")
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    bot_role = await IDENTITY.bot_role(gateway, group_id, force=True)
    enabled = MANAGER.is_group_enabled(group_id)
    safeguard = SAFEGUARD.config(group_id)
    approval = APPROVAL.config(group_id)
    counts = SAFEGUARD.daily_counts(group_id)
    notice = CATALOG.format_fallback(
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
    reply = await compose_reply(
        gateway,
        event,
        scenario="admin_status",
        fallback=notice,
        facts={"group_id": group_id, "enabled": enabled, "daily": counts},
    )
    await matcher.finish(reply)


@admin_on_cmd.handle()
async def handle_admin_on(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin on")
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    MANAGER.set_group_enabled(group_id, True)
    reply = await compose_reply(
        gateway,
        event,
        scenario="admin_on",
        fallback=CATALOG.format_fallback("admin_on", group_id=group_id),
        facts={"group_id": group_id, "enabled": True},
    )
    await matcher.finish(reply)


@admin_off_cmd.handle()
async def handle_admin_off(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin off")
    args = command_args(event, prefix_words=2)
    group_id = args[0] if args else event.group_openid
    MANAGER.set_group_enabled(group_id, False)
    reply = await compose_reply(
        gateway,
        event,
        scenario="admin_off",
        fallback=CATALOG.format_fallback("admin_off", group_id=group_id),
        facts={"group_id": group_id, "enabled": False},
    )
    await matcher.finish(reply)


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
                CATALOG.format_fallback(
                    "config_updated",
                    group_id=group_id,
                    target=args[1],
                    value=getattr(updated, field_name),
                )
            )
    except (ConfigError, ValueError) as exc:
        await matcher.finish(f"Config error: {exc}")

    await matcher.finish("Usage: /admin config <get|set> <module>[.<field>] [value]")


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
        await matcher.finish(CATALOG.format_fallback("log_empty", group_id=group_id))
    header = CATALOG.format_fallback(
        "log_header", group_id=group_id, count=len(records)
    )
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
    SAFEGUARD.add_exempt(event.group_openid, member_id)
    await matcher.finish(CATALOG.format_fallback("exempt_added", member_id=member_id))


@admin_unexempt_cmd.handle()
async def handle_admin_unexempt(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "admin unexempt")
    args = command_args(event, prefix_words=2)
    if not args:
        await matcher.finish("Usage: /admin unexempt <member>")
    member_id = args[0].lstrip("@")
    SAFEGUARD.remove_exempt(event.group_openid, member_id)
    await matcher.finish(CATALOG.format_fallback("exempt_removed", member_id=member_id))


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
