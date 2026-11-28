"""Moderation action commands (/warn, /mute, /kick, /ban, /recall, /approve)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import re

from opsmesh import on_regex
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import ServiceManager
from qq_admin.modules import ActionOutcome, WarningCategory

from .helpers import check_access, event_text, finish_reply, render_outcome

Action = Callable[..., Awaitable[ActionOutcome | str]]


async def warn(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    category: str | None = None,
    reason: str | None = None,
) -> ActionOutcome:
    kind: WarningCategory = (
        "ad" if category == "ad" else ("abuse" if category == "abuse" else "spam")
    )
    return await manager.moderation.warn(
        gateway,
        event.group_openid,
        member,
        category=kind,
        reason=reason or "manual warning",
        operator_id=event.get_user_id(),
    )


async def mute(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    duration: str | None = None,
    reason: str | None = None,
) -> ActionOutcome:
    return await manager.moderation.mute(
        gateway,
        event.group_openid,
        member,
        duration=duration or "10m",
        reason=reason or "manual mute",
        operator_id=event.get_user_id(),
    )


async def unmute(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, *, member: str
) -> ActionOutcome:
    return await manager.moderation.unmute(
        gateway, event.group_openid, member, operator_id=event.get_user_id()
    )


async def kick(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    reason: str | None = None,
) -> ActionOutcome:
    return await manager.moderation.kick(
        gateway,
        event.group_openid,
        member,
        reason=reason or "manual kick",
        operator_id=event.get_user_id(),
    )


async def ban(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    reason: str | None = None,
) -> ActionOutcome:
    return await manager.moderation.ban(
        gateway,
        event.group_openid,
        member,
        reason=reason or "manual ban",
        operator_id=event.get_user_id(),
    )


async def unban(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, *, member: str
) -> ActionOutcome:
    return await manager.moderation.unban(
        gateway, event.group_openid, member, operator_id=event.get_user_id()
    )


async def recall(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    message_id: str | None = None,
    reason: str | None = None,
) -> ActionOutcome | str:
    reference = event.message_reference
    target = message_id or (reference.message_id if reference else "")
    if not target:
        return "Usage: /recall <message_id> (or reply to the message)"
    return await manager.moderation.recall(
        gateway,
        event.group_openid,
        target,
        reason=reason or "manual recall",
        operator_id=event.get_user_id(),
    )


async def approve(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    request_id: str | None = None,
) -> ActionOutcome:
    return await manager.approval.approve(
        gateway,
        event.group_openid,
        member,
        request_id=request_id,
        operator_id=event.get_user_id(),
    )


async def reject(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    *,
    member: str,
    reason: str | None = None,
) -> ActionOutcome:
    return await manager.approval.reject(
        gateway,
        event.group_openid,
        member,
        reason=reason or "manual reject",
        operator_id=event.get_user_id(),
    )


@dataclass(frozen=True, slots=True)
class ActionCommand:
    name: str
    pattern: re.Pattern[str]
    usage: str
    run: Action


_MEMBER = r"@?(?P<member>\S+)"
_REASON = r"(?:\s+(?P<reason>.+))?"

ACTION_COMMANDS = [
    ActionCommand(
        "warn",
        re.compile(
            rf"^/warn\s+{_MEMBER}(?:\s+(?P<category>spam|abuse|ad))?{_REASON}$", re.I
        ),
        "/warn <member> [spam|abuse|ad] [reason]",
        warn,
    ),
    ActionCommand(
        "mute",
        re.compile(
            rf"^/mute\s+{_MEMBER}(?:\s+(?P<duration>\d+[smhd]?))?{_REASON}$", re.I
        ),
        "/mute <member> [10m|2h|1d] [reason]",
        mute,
    ),
    ActionCommand(
        "unmute",
        re.compile(rf"^/unmute\s+{_MEMBER}$", re.I),
        "/unmute <member>",
        unmute,
    ),
    ActionCommand(
        "kick",
        re.compile(rf"^/kick\s+{_MEMBER}{_REASON}$", re.I),
        "/kick <member> [reason]",
        kick,
    ),
    ActionCommand(
        "ban",
        re.compile(rf"^/ban\s+{_MEMBER}{_REASON}$", re.I),
        "/ban <member> [reason]",
        ban,
    ),
    ActionCommand(
        "unban", re.compile(rf"^/unban\s+{_MEMBER}$", re.I), "/unban <member>", unban
    ),
    ActionCommand(
        "recall",
        re.compile(r"^/recall(?:\s+(?P<message_id>\S+))?" + _REASON + "$", re.I),
        "/recall [message_id] [reason]",
        recall,
    ),
    ActionCommand(
        "approve",
        re.compile(rf"^/approve\s+{_MEMBER}(?:\s+(?P<request_id>\S+))?$", re.I),
        "/approve <member> [join_request_id]",
        approve,
    ),
    ActionCommand(
        "reject",
        re.compile(rf"^/reject\s+{_MEMBER}{_REASON}$", re.I),
        "/reject <member> [reason]",
        reject,
    ),
]


async def run_action(
    command: ActionCommand,
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
) -> str | None:
    """Authorize, parse arguments, execute, and render one action command."""
    allowed, denial = await check_access(
        gateway, event, manager, minimum_role="admin", command_name=command.name
    )
    if not allowed:
        return denial
    match = command.pattern.match(event_text(event))
    if match is None:
        return f"Usage: {command.usage}"
    arguments = {k: v.strip() for k, v in match.groupdict().items() if v}
    result = await command.run(gateway, event, manager, **arguments)
    if isinstance(result, str):
        return result
    target = arguments.get("member") or arguments.get("message_id", "")
    return await render_outcome(gateway, event, manager, result, target_id=target)


def _endpoint(command: ActionCommand, manager: ServiceManager):
    async def _handle(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        await finish_reply(matcher, await run_action(command, gateway, event, manager))

    return _handle


def bind_action_commands(manager: ServiceManager) -> None:
    for command in ACTION_COMMANDS:
        on_regex(
            rf"^/{command.name}(?:\s|$)", flags=re.IGNORECASE, priority=1, block=True
        ).append_handler(_endpoint(command, manager))


__all__ = ["ACTION_COMMANDS", "ActionCommand", "bind_action_commands", "run_action"]
