"""Read-only inspection commands: /shutlist /blacklist /requests /member."""

import re

from opsmesh import on_regex
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import ServiceManager

from .helpers import check_access, event_text, finish_reply

_MEMBER_RE = re.compile(r"^/member\s+@?(?P<member>\S+)$", re.IGNORECASE)


async def shutlist(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str:
    setting = await gateway.get_group_mute_setting(event.group_openid)
    if not setting.members:
        return manager.catalog.format_fallback(
            "shutlist_empty", mode=setting.global_rule.mode
        )
    lines = [
        f"- {m.member_openid} until {m.mute_expire_at}" for m in setting.members[:25]
    ]
    return "\n".join([f"global_mode={setting.global_rule.mode}", *lines])


async def blacklist(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str:
    result = await gateway.get_group_member_blacklist(event.group_openid)
    if not result.users:
        return manager.catalog.format_fallback("blacklist_empty")
    return "\n".join(
        f"- {u.member_openid} ({u.username or '-'})" for u in result.users[:25]
    )


async def requests(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str:
    page = await gateway.get_group_join_request_list(event.group_openid)
    if not page.list:
        return manager.catalog.format_fallback("requests_empty")
    return "\n".join(
        f"- {r.member_openid} id={r.join_request_id} risk={r.risk_tips or 'none'}"
        for r in page.list[:20]
    )


async def member(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str:
    match = _MEMBER_RE.match(event_text(event))
    if match is None:
        return "Usage: /member <member>"
    info = await gateway.get_group_member(event.group_openid, match.group("member"))
    manager.safeguard.mark_member_verified(event.group_openid, info.member_openid)
    return (
        f"member={info.member_openid} role={info.member_role} "
        f"bot={info.bot} joined_at={info.joined_at}"
    )


QUERY_COMMANDS = {
    "shutlist": shutlist,
    "blacklist": blacklist,
    "requests": requests,
    "member": member,
}


async def run_query(
    name: str, gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str | None:
    allowed, denial = await check_access(
        gateway, event, manager, minimum_role="admin", command_name=name
    )
    if not allowed:
        return denial
    try:
        return await QUERY_COMMANDS[name](gateway, event, manager)
    except Exception as exc:
        return manager.catalog.format_fallback("action_failed", reason=exc)


def _endpoint(name: str, manager: ServiceManager):
    async def _handle(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        await finish_reply(matcher, await run_query(name, gateway, event, manager))

    return _handle


def bind_query_commands(manager: ServiceManager) -> None:
    for name in QUERY_COMMANDS:
        on_regex(
            rf"^/{name}(?:\s|$)", flags=re.IGNORECASE, priority=1, block=True
        ).append_handler(_endpoint(name, manager))


__all__ = ["QUERY_COMMANDS", "bind_query_commands", "run_query"]
