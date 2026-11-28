"""Join-request commands (`/requests`, `/approve`, `/reject`) and notice listeners."""

from opsmesh.params import CommandArg
from opsmesh.plugin import on_command, on_type
from qq import Gateway, GroupJoinRequestEvent, GroupMessageEvent, Message

from qq_admin.services import (
    approve_join_request,
    decline_join_request,
    get_services,
    list_join_requests,
)

from . import ADMIN_PERMISSION, finish_outcome, make_command_context

requests_cmd = on_command(
    "requests", permission=ADMIN_PERMISSION, priority=10, block=True
)
approve_cmd = on_command(
    "approve", permission=ADMIN_PERMISSION, priority=10, block=True
)
reject_cmd = on_command("reject", permission=ADMIN_PERMISSION, priority=10, block=True)
join_notice = on_type(GroupJoinRequestEvent, priority=10, block=False)


@requests_cmd.handle()
async def handle_requests(gateway: Gateway, event: GroupMessageEvent) -> None:
    await finish_outcome(
        requests_cmd, list_join_requests(make_command_context(gateway, event))
    )


@approve_cmd.handle()
async def handle_approve(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await approve_cmd.finish("Usage: /approve <member_openid> [join_request_id]")
    ctx = make_command_context(gateway, event)
    await finish_outcome(
        approve_cmd,
        approve_join_request(
            ctx,
            member_openid=parts[0],
            join_request_id=parts[1] if len(parts) > 1 else None,
        ),
    )


@reject_cmd.handle()
async def handle_reject(
    gateway: Gateway, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await reject_cmd.finish("Usage: /reject <member_openid> [reason]")
    ctx = make_command_context(gateway, event)
    await finish_outcome(
        reject_cmd,
        decline_join_request(
            ctx,
            member_openid=parts[0],
            reject_reason=" ".join(parts[1:]) if len(parts) > 1 else None,
        ),
    )


@join_notice.handle()
async def handle_join_notice(gateway: Gateway, event: GroupJoinRequestEvent) -> None:
    await get_services().auto_approve.handle_event(gateway, event)


__all__ = ["approve_cmd", "join_notice", "reject_cmd", "requests_cmd"]
