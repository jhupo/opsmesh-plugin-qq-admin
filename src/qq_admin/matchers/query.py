"""Group and member inspection commands (`/groupinfo`, `/member`, `/members`)."""

from opsmesh.params import CommandArg
from opsmesh.plugin import on_command
from qq import Gateway, GroupMessageEvent, Message

from qq_admin.services import get_group_info, get_member, list_members

from . import (
    ADMIN_PERMISSION,
    extract_target_and_rest,
    finish_outcome,
    make_command_context,
)

group_info_cmd = on_command(
    "groupinfo", permission=ADMIN_PERMISSION, priority=10, block=True
)
member_cmd = on_command("member", permission=ADMIN_PERMISSION, priority=10, block=True)
members_cmd = on_command(
    "members", permission=ADMIN_PERMISSION, priority=10, block=True
)


@group_info_cmd.handle()
async def handle_group_info(gateway: Gateway, event: GroupMessageEvent) -> None:
    await finish_outcome(
        group_info_cmd, get_group_info(make_command_context(gateway, event))
    )


@member_cmd.handle()
async def handle_member(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    target, _ = extract_target_and_rest(args)
    if not target:
        await member_cmd.finish("Usage: /member <member_openid>")
    ctx = make_command_context(gateway, event)
    await finish_outcome(member_cmd, get_member(ctx, member_openid=target))


@members_cmd.handle()
async def handle_members(gateway: Gateway, event: GroupMessageEvent) -> None:
    await finish_outcome(
        members_cmd, list_members(make_command_context(gateway, event))
    )


__all__ = ["group_info_cmd", "member_cmd", "members_cmd"]
