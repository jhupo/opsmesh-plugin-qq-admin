"""Direct OpsMesh read-only inspection commands."""

from opsmesh import on_command
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.modules import SAFEGUARD
from qq_admin.prompts import notice

from .helpers import command_args, require_admin

shutlist_cmd = on_command("shutlist", priority=1, block=True)
blacklist_cmd = on_command("blacklist", priority=1, block=True)
requests_cmd = on_command("requests", priority=1, block=True)
member_cmd = on_command("member", priority=1, block=True)


@shutlist_cmd.handle()
async def handle_shutlist(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "shutlist")
    setting = await gateway.get_group_mute_setting(event.group_openid)
    if not setting.members:
        await matcher.finish(notice("shutlist_empty", mode=setting.global_rule.mode))
    lines = [
        f"- {m.member_openid} until {m.mute_expire_at}" for m in setting.members[:25]
    ]
    await matcher.finish("\n".join([f"global_mode={setting.global_rule.mode}", *lines]))


@blacklist_cmd.handle()
async def handle_blacklist(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "blacklist")
    result = await gateway.get_group_member_blacklist(event.group_openid)
    if not result.users:
        await matcher.finish(notice("blacklist_empty"))
    await matcher.finish(
        "\n".join(
            f"- {u.member_openid} ({u.username or '-'})" for u in result.users[:25]
        )
    )


@requests_cmd.handle()
async def handle_requests(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "requests")
    page = await gateway.get_group_join_request_list(event.group_openid)
    if not page.list:
        await matcher.finish(notice("requests_empty"))
    await matcher.finish(
        "\n".join(
            f"- {r.member_openid} id={r.join_request_id} risk={r.risk_tips or 'none'}"
            for r in page.list[:20]
        )
    )


@member_cmd.handle()
async def handle_member(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "member")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /member <member>")
    target = args[0].lstrip("@")
    info = await gateway.get_group_member(event.group_openid, target)
    SAFEGUARD.mark_member_verified(event.group_openid, info.member_openid)
    await matcher.finish(
        f"member={info.member_openid} role={info.member_role} "
        f"bot={info.bot} joined_at={info.joined_at}"
    )
