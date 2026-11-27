"""Moderation commands (`/warn`, `/unwarn`, `/mute`, `/unmute`, `/kick`, `/recall`)."""

from opsmesh.params import CommandArg
from opsmesh.plugin import on_command
from qq import Gateway, GroupMessageEvent, Message

from qq_admin.api import (
    clear_warnings,
    get_mute_setting,
    kick_member,
    mute_member,
    recall_message,
    unmute_member,
    warn_member,
)
from qq_admin.typing import ViolationType

from . import (
    ADMIN_PERMISSION,
    extract_target_and_rest,
    finish_outcome,
    make_command_context,
    parse_duration_seconds,
)

warn_cmd = on_command("warn", permission=ADMIN_PERMISSION, priority=10, block=True)
unwarn_cmd = on_command("unwarn", permission=ADMIN_PERMISSION, priority=10, block=True)
mute_cmd = on_command("mute", permission=ADMIN_PERMISSION, priority=10, block=True)
unmute_cmd = on_command("unmute", permission=ADMIN_PERMISSION, priority=10, block=True)
shutlist_cmd = on_command(
    "shutlist", permission=ADMIN_PERMISSION, priority=10, block=True
)
kick_cmd = on_command("kick", permission=ADMIN_PERMISSION, priority=10, block=True)
recall_cmd = on_command("recall", permission=ADMIN_PERMISSION, priority=10, block=True)


@warn_cmd.handle()
async def handle_warn(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, rest = extract_target_and_rest(args)
    if not target:
        await warn_cmd.finish("Usage: /warn <member_openid> [reason]")
    ctx = make_command_context(gateway, event)
    await finish_outcome(
        warn_cmd,
        warn_member(
            ctx,
            member_openid=target,
            violation_type=ViolationType.OTHER,
            reason=" ".join(rest),
        ),
    )


@unwarn_cmd.handle()
async def handle_unwarn(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, _ = extract_target_and_rest(args)
    if not target:
        await unwarn_cmd.finish("Usage: /unwarn <member_openid>")
    ctx = make_command_context(gateway, event)
    await finish_outcome(unwarn_cmd, clear_warnings(ctx, member_openid=target))


@mute_cmd.handle()
async def handle_mute(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, rest = extract_target_and_rest(args)
    if not target:
        await mute_cmd.finish(
            "Usage: /mute <member_openid> [duration e.g. 10m] [reason]"
        )
    duration = parse_duration_seconds(rest[0]) if rest else 600
    reason = " ".join(rest[1:]) if len(rest) > 1 else ""
    ctx = make_command_context(gateway, event)
    await finish_outcome(
        mute_cmd,
        mute_member(
            ctx, member_openid=target, duration_seconds=duration, reason=reason
        ),
    )


@unmute_cmd.handle()
async def handle_unmute(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, _ = extract_target_and_rest(args)
    if not target:
        await unmute_cmd.finish("Usage: /unmute <member_openid>")
    ctx = make_command_context(gateway, event)
    await finish_outcome(unmute_cmd, unmute_member(ctx, member_openid=target))


@shutlist_cmd.handle()
async def handle_shutlist(gateway: Gateway, event: GroupMessageEvent) -> None:
    await finish_outcome(
        shutlist_cmd, get_mute_setting(make_command_context(gateway, event))
    )


@kick_cmd.handle()
async def handle_kick(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, rest = extract_target_and_rest(args)
    if not target:
        await kick_cmd.finish("Usage: /kick <member_openid> [--ban] [reason]")
    ctx = make_command_context(gateway, event)
    await finish_outcome(
        kick_cmd,
        kick_member(
            ctx,
            member_openid=target,
            add_to_blacklist="--ban" in rest,
            reason=" ".join(t for t in rest if t != "--ban"),
        ),
    )


@recall_cmd.handle()
async def handle_recall(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    msg_id = args.extract_plain_text().strip() or (
        event.message_reference.message_id if event.message_reference else ""
    )
    if not msg_id:
        await recall_cmd.finish("Usage: /recall <message_id> or reply to a message.")
    ctx = make_command_context(gateway, event)
    await finish_outcome(recall_cmd, recall_message(ctx, message_id=msg_id))


__all__ = [
    "kick_cmd",
    "mute_cmd",
    "recall_cmd",
    "shutlist_cmd",
    "unmute_cmd",
    "unwarn_cmd",
    "warn_cmd",
]
