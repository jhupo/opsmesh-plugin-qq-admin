"""/admin console: group switch, online module config, sessions, audit."""

from collections.abc import Awaitable, Callable
import json
import re

from opsmesh import on_regex
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.exception import ConfigError
from qq_admin.manager import ServiceManager

from .helpers import (
    check_access,
    compose_reply,
    event_text,
    finish_reply,
    render_outcome,
)

AdminHandler = Callable[
    [Gateway, GroupMessageEvent, ServiceManager, list[str]], Awaitable[str | None]
]

_ADMIN_RE = re.compile(r"^/admin(?:\s+(?P<rest>.*))?$", re.IGNORECASE)
USAGE = (
    "/admin status | on | off | config get <module>[.<field>] | "
    "config set <module>.<field> <value> | session [mode fresh|shared | reset] | "
    "log [n] | perm [member] | exempt <member> | unexempt <member> | undo <member>"
)


async def status(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    group_id = args[0] if args else event.group_openid
    bot_role = await manager.identity.bot_role(gateway, group_id, force=True)
    enabled = manager.is_group_enabled(group_id)
    safeguard = manager.safeguard.config(group_id)
    approval = manager.approval.config(group_id)
    counts = manager.safeguard.daily_counts(group_id)
    session_mode = manager.decision_agent.session_mode(group_id)
    notice = manager.catalog.format_fallback(
        "admin_status",
        group_id=group_id,
        bot_role=bot_role,
        status=f"{'on' if enabled else 'off'} (session={session_mode})",
        mute_count=counts["mute"],
        mute_limit=safeguard.daily_mute_limit,
        kick_count=counts["kick"],
        kick_limit=safeguard.daily_kick_limit,
        approve_count=counts["approve"],
        approve_limit=approval.daily_approve_limit,
        reject_count=counts["reject"],
        reject_limit=approval.daily_reject_limit,
    )
    return await compose_reply(
        gateway,
        event,
        manager,
        scenario="admin_status",
        fallback=notice,
        facts={"enabled": enabled, "session_mode": session_mode, "daily": counts},
    )


async def enable(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    return await _switch_group(gateway, event, manager, args, enabled=True)


async def disable(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    return await _switch_group(gateway, event, manager, args, enabled=False)


async def _switch_group(
    gateway: Gateway,
    event: GroupMessageEvent,
    manager: ServiceManager,
    args: list[str],
    *,
    enabled: bool,
) -> str:
    group_id = args[0] if args else event.group_openid
    manager.set_group_enabled(group_id, enabled)
    scenario = "admin_on" if enabled else "admin_off"
    return await compose_reply(
        gateway,
        event,
        manager,
        scenario=scenario,
        fallback=manager.catalog.format_fallback(scenario, group_id=group_id),
        facts={"enabled": enabled},
    )


async def config(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    del gateway
    group_id = event.group_openid
    try:
        if len(args) >= 2 and args[0] == "get":
            return _read_config(manager, group_id, args[1])
        if len(args) >= 3 and args[0] == "set":
            return _write_config(manager, group_id, args[1], " ".join(args[2:]))
    except ConfigError as exc:
        return f"Config error: {exc}"
    except ValueError as exc:
        return f"Config error: {exc}"
    return f"Usage: {USAGE}"


def _read_config(manager: ServiceManager, group_id: str, target: str) -> str:
    module_name, _, field_name = target.partition(".")
    values = manager.module(module_name).config(group_id).model_dump()
    if not field_name:
        return json.dumps(values, ensure_ascii=False)
    if field_name not in values:
        raise ConfigError(f"Unknown field: {target}")
    return f"{target} = {json.dumps(values[field_name], ensure_ascii=False)}"


def _write_config(
    manager: ServiceManager, group_id: str, target: str, raw_value: str
) -> str:
    module_name, _, field_name = target.partition(".")
    if not field_name:
        raise ConfigError("Expected <module>.<field>")
    updated = manager.module(module_name).update_config(group_id, field_name, raw_value)
    return manager.catalog.format_fallback(
        "config_updated",
        group_id=group_id,
        target=target,
        value=getattr(updated, field_name),
    )


async def session(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    del gateway
    group_id = event.group_openid
    if len(args) >= 2 and args[0] == "mode" and args[1] in {"fresh", "shared"}:
        mode = "shared" if args[1] == "shared" else "fresh"
        manager.decision_agent.set_session_mode(mode, group_id=group_id)
        manager.reply_agent.set_session_mode(mode, group_id=group_id)
        return manager.catalog.format_fallback(
            "session_mode_updated", group_id=group_id, mode=mode
        )
    if args and args[0] == "reset":
        await manager.reset_group_sessions(group_id)
        return manager.catalog.format_fallback("session_reset", group_id=group_id)
    return f"session_mode={manager.decision_agent.session_mode(group_id)}"


async def logs(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    del gateway
    group_id = event.group_openid
    limit = int(args[0]) if args and args[0].isdigit() else None
    records = manager.audit.recent_logs(group_id, limit=limit)
    if not records:
        return manager.catalog.format_fallback("log_empty", group_id=group_id)
    header = manager.catalog.format_fallback(
        "log_header", group_id=group_id, count=len(records)
    )
    lines = [
        f"- [{r.action}] {r.target_id} by {r.operator_id} ok={r.succeeded} ({r.reason})"
        for r in records
    ]
    return "\n".join([header, *lines])


async def permissions(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    member_id = args[0].lstrip("@") if args else event.get_user_id()
    _, trace = await manager.identity.authorize(
        gateway,
        event.group_openid,
        member_id,
        minimum_role="global_admin",
        force_refresh=True,
    )
    return (
        f"member={trace.member_id} role={trace.member_role} bot_role={trace.bot_role} "
        f"global_admin={trace.is_global_admin} allowed={trace.allowed}\n"
        + "\n".join(f"- {step}" for step in trace.steps)
    )


async def exempt(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    del gateway
    if not args:
        return f"Usage: {USAGE}"
    member_id = args[0].lstrip("@")
    manager.safeguard.add_exempt(event.group_openid, member_id)
    return manager.catalog.format_fallback("exempt_added", member_id=member_id)


async def unexempt(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    del gateway
    if not args:
        return f"Usage: {USAGE}"
    member_id = args[0].lstrip("@")
    manager.safeguard.remove_exempt(event.group_openid, member_id)
    return manager.catalog.format_fallback("exempt_removed", member_id=member_id)


async def undo(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager, args: list[str]
) -> str:
    if not args:
        return f"Usage: {USAGE}"
    member_id = args[0].lstrip("@")
    outcome = await manager.moderation.undo(
        gateway, event.group_openid, member_id, operator_id=event.get_user_id()
    )
    return await render_outcome(gateway, event, manager, outcome, target_id=member_id)


SUBCOMMANDS: dict[str, AdminHandler] = {
    "status": status,
    "on": enable,
    "off": disable,
    "config": config,
    "session": session,
    "log": logs,
    "perm": permissions,
    "exempt": exempt,
    "unexempt": unexempt,
    "undo": undo,
}


async def run_admin(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> str | None:
    """Authorize the sender, then dispatch the /admin subcommand."""
    match = _ADMIN_RE.match(event_text(event))
    if match is None:
        return None
    name, *args = (match.group("rest") or "status").split()
    handler = SUBCOMMANDS.get(name.lower())
    if handler is None:
        return f"Usage: {USAGE}"
    allowed, denial = await check_access(
        gateway, event, manager, minimum_role="global_admin", command_name=name.lower()
    )
    if not allowed:
        return denial
    return await handler(gateway, event, manager, args)


def bind_admin_commands(manager: ServiceManager) -> None:
    @on_regex(r"^/admin(?:\s|$)", flags=re.IGNORECASE, priority=1, block=True).handle()
    async def _admin(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        await finish_reply(matcher, await run_admin(gateway, event, manager))


__all__ = ["SUBCOMMANDS", "bind_admin_commands", "run_admin"]
