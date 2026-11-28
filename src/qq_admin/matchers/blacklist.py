"""Blacklist management commands (`/banlist`, `/ban`, `/unban`)."""

from opsmesh.params import CommandArg
from opsmesh.plugin import on_command
from qq import Gateway, GroupMessageEvent, Message

from qq_admin.services import add_blacklist, list_blacklist, remove_blacklist

from . import (
    ADMIN_PERMISSION,
    extract_target_and_rest,
    finish_outcome,
    make_command_context,
)

banlist_cmd = on_command(
    "banlist", permission=ADMIN_PERMISSION, priority=10, block=True
)
ban_cmd = on_command("ban", permission=ADMIN_PERMISSION, priority=10, block=True)
unban_cmd = on_command("unban", permission=ADMIN_PERMISSION, priority=10, block=True)


@banlist_cmd.handle()
async def handle_banlist(gateway: Gateway, event: GroupMessageEvent) -> None:
    await finish_outcome(
        banlist_cmd, list_blacklist(make_command_context(gateway, event))
    )


@ban_cmd.handle()
async def handle_ban(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, _ = extract_target_and_rest(args)
    if not target:
        await ban_cmd.finish("Usage: /ban <member_openid>")
    ctx = make_command_context(gateway, event)
    await finish_outcome(ban_cmd, add_blacklist(ctx, member_openids=[target]))


@unban_cmd.handle()
async def handle_unban(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, _ = extract_target_and_rest(args)
    if not target:
        await unban_cmd.finish("Usage: /unban <member_openid>")
    ctx = make_command_context(gateway, event)
    await finish_outcome(unban_cmd, remove_blacklist(ctx, member_openids=[target]))


__all__ = ["ban_cmd", "banlist_cmd", "unban_cmd"]
