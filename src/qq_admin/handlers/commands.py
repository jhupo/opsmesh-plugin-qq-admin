"""Tiered OpsMesh slash command console with ReplyAgent contextual responses."""

from typing import Any, Literal

from opsmesh import on_command
from opsmesh.adapters import Message
from opsmesh.matcher import Matcher
from opsmesh.params import CommandArg
from qq import Gateway, GroupMessageEvent

from qq_admin.agents import ReplyContext, generate_reply
from qq_admin.config import render_fallback_message
from qq_admin.moderation import (
    ActionResult,
    approve_join,
    ban_member,
    evaluate_command_permission,
    is_group_enabled,
    kick_member,
    mute_member,
    recall_message,
    refresh_bot_role,
    refresh_member_role,
    reject_join,
    unban_member,
    unmute_member,
    warn_member,
)
from qq_admin.state import PluginRuntime


async def _compose_reply(
    gateway: Gateway,
    event: GroupMessageEvent,
    runtime: PluginRuntime,
    *,
    scenario: str,
    fallback: str,
    target_openid: str = "",
    executed_actions: list[str] | None = None,
    facts: dict[str, Any] | None = None,
) -> str:
    """Delegate phrasing to ReplyAgent with live state, falling back if disabled."""
    if not runtime.config.llm.enabled:
        return fallback
    gid = event.group_openid
    uid = event.get_user_id()
    bot_role = await refresh_bot_role(gateway, runtime.config, runtime.state, gid)
    actor_role = await refresh_member_role(
        gateway, runtime.config, runtime.state, gid, uid
    )
    return await generate_reply(
        ReplyContext(
            runtime=runtime,
            group_openid=gid,
            bot_role=bot_role,
            scenario=scenario,
            actor_openid=uid,
            actor_role=actor_role,
            target_openid=target_openid,
            executed_actions=executed_actions or [],
            facts=facts or {},
            fallback_text=fallback,
        )
    )


async def _finish_action(
    gateway: Gateway,
    event: GroupMessageEvent,
    matcher: Matcher,
    runtime: PluginRuntime,
    res: ActionResult,
    *,
    target_openid: str = "",
) -> None:
    scenario = (
        "guard_blocked"
        if res.blocked_step
        else ("command_executed" if res.ok else "command_failed")
    )
    text = await _compose_reply(
        gateway,
        event,
        runtime,
        scenario=scenario,
        fallback=res.summary,
        target_openid=target_openid,
        executed_actions=[res.action] if res.ok else [],
        facts={
            "action": res.action,
            "ok": res.ok,
            "blocked_step": res.blocked_step,
            "detail": res.summary,
        },
    )
    await matcher.finish(text)


async def _authorize(
    gateway: Gateway,
    event: GroupMessageEvent,
    matcher: Matcher,
    runtime: PluginRuntime,
    *,
    minimum_role: Literal["member", "admin", "owner", "global"] = "admin",
    command_name: str = "",
) -> bool:
    allowed, trace = await evaluate_command_permission(
        gateway,
        runtime.config,
        runtime.state,
        event.group_openid,
        event.get_user_id(),
        minimum_role=minimum_role,
        command_name=command_name,
    )
    if allowed:
        return True
    if runtime.config.admin.deny_response == "reply":
        fallback = render_fallback_message(runtime.prompts, "denied")
        text = await _compose_reply(
            gateway,
            event,
            runtime,
            scenario="permission_denied",
            fallback=fallback,
            facts={"command": command_name, "reason": trace.reason},
        )
        await matcher.finish(text)
    await matcher.finish()
    return False


def _split_args(arg: Message) -> list[str]:
    return [tok for tok in arg.extract_plain_text().strip().split() if tok]


async def handle_admin_console(
    gateway: Gateway,
    event: GroupMessageEvent,
    matcher: Matcher,
    runtime: PluginRuntime,
    tokens: list[str],
) -> None:
    """Handle /admin <status|on|off|log|perm|exempt|unexempt|undo>."""
    sub = tokens[0].lower() if tokens else "status"
    rest = tokens[1:]
    if not await _authorize(
        gateway, event, matcher, runtime, minimum_role="owner", command_name=sub
    ):
        return

    gid = event.group_openid
    if sub == "status":
        bot_role = await refresh_bot_role(gateway, runtime.config, runtime.state, gid)
        enabled = is_group_enabled(runtime.config, runtime.state, gid)
        sf = runtime.config.safeguard
        aa = runtime.config.auto_approve
        mute_lim = "unlimited" if bot_role == "owner" else str(sf.daily_mute_limit)
        kick_lim = "unlimited" if bot_role == "owner" else str(sf.daily_kick_limit)
        appr_lim = "unlimited" if bot_role == "owner" else str(aa.daily_approve_limit)
        rej_lim = "unlimited" if bot_role == "owner" else str(aa.daily_reject_limit)
        text = render_fallback_message(
            runtime.prompts,
            "admin_status",
            group_openid=gid,
            bot_role=bot_role,
            status="ON" if enabled else "PAUSED",
            mute_count=runtime.state.get_daily_count(gid, "mute"),
            mute_limit=mute_lim,
            kick_count=runtime.state.get_daily_count(gid, "kick"),
            kick_limit=kick_lim,
            approve_count=runtime.state.get_daily_count(gid, "approve"),
            approve_limit=appr_lim,
            reject_count=runtime.state.get_daily_count(gid, "reject"),
            reject_limit=rej_lim,
        )
        await matcher.finish(text)

    if sub == "on":
        runtime.state.disabled_groups.discard(gid)
        if (
            runtime.config.auto_moderate.enabled_groups
            and gid not in runtime.config.auto_moderate.enabled_groups
        ):
            runtime.config.auto_moderate.enabled_groups.append(gid)
        fallback = render_fallback_message(
            runtime.prompts, "admin_on", group_openid=gid
        )
        await matcher.finish(
            await _compose_reply(
                gateway,
                event,
                runtime,
                scenario="admin_toggle",
                fallback=fallback,
                facts={"enabled": True},
            )
        )

    if sub == "off":
        runtime.state.disabled_groups.add(gid)
        fallback = render_fallback_message(
            runtime.prompts, "admin_off", group_openid=gid
        )
        await matcher.finish(
            await _compose_reply(
                gateway,
                event,
                runtime,
                scenario="admin_toggle",
                fallback=fallback,
                facts={"enabled": False},
            )
        )

    if sub == "log":
        limit = (
            int(rest[0])
            if rest and rest[0].isdigit()
            else runtime.config.logging.default_log_lines
        )
        entries = runtime.state.get_op_logs(gid, limit)
        if not entries:
            await matcher.finish(
                render_fallback_message(
                    runtime.prompts, "admin_log_empty", group_openid=gid
                )
            )
        header = render_fallback_message(
            runtime.prompts, "admin_log_header", group_openid=gid, count=len(entries)
        )
        lines = [header]
        for item in entries:
            mark = "OK" if item.success else "ERR"
            ts = item.timestamp.strftime("%m-%d %H:%M")
            lines.append(
                f"[{ts}] {mark} {item.action} target={item.target_openid} "
                f"by={item.operator_openid} ({item.reason})"
            )
        await matcher.finish("\n".join(lines))

    if sub == "perm":
        target = rest[0].lstrip("@") if rest else event.get_user_id()
        _, trace = await evaluate_command_permission(
            gateway,
            runtime.config,
            runtime.state,
            gid,
            target,
            minimum_role="owner",
            force_refresh=True,
        )
        bot_role = await refresh_bot_role(
            gateway, runtime.config, runtime.state, gid, force=True
        )
        trace.add("bot_role", bot_role in ("owner", "admin"), f"bot_role={bot_role}")
        in_protected = target in runtime.config.safeguard.protected_users
        in_exempt = target in runtime.state.exempt_users.get(gid, set())
        trace.add(
            "target_protected",
            in_protected or in_exempt,
            f"protected={in_protected}, exempt={in_exempt}",
        )
        await matcher.finish(trace.format_text())

    if sub == "exempt" and rest:
        member = rest[0].lstrip("@")
        runtime.state.exempt_users.setdefault(gid, set()).add(member)
        await matcher.finish(
            render_fallback_message(
                runtime.prompts, "admin_exempt_added", member_openid=member
            )
        )

    if sub == "unexempt" and rest:
        member = rest[0].lstrip("@")
        runtime.state.exempt_users.get(gid, set()).discard(member)
        await matcher.finish(
            render_fallback_message(
                runtime.prompts, "admin_exempt_removed", member_openid=member
            )
        )

    if sub == "undo" and rest:
        member = rest[0].lstrip("@")
        res = await unmute_member(
            gateway,
            runtime,
            group_openid=gid,
            member_openid=member,
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    await matcher.finish(
        "Usage: /admin <status|on|off|log|perm|exempt|unexempt|undo> [args]"
    )


def register_commands(runtime: PluginRuntime) -> None:
    """Register the 21 Official QQ v2 group administration commands."""
    admin_cmd = on_command("admin", priority=1, block=True)

    @admin_cmd.handle()
    async def _on_admin(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        await handle_admin_console(gateway, event, matcher, runtime, _split_args(arg))

    warn_cmd = on_command("warn", priority=1, block=True)

    @warn_cmd.handle()
    async def _on_warn(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(gateway, event, matcher, runtime, command_name="warn"):
            return
        tokens = _split_args(arg)
        if len(tokens) < 2 or tokens[1].lower() not in ("spam", "abuse", "ad"):
            await matcher.finish(
                "Usage: /warn <member_openid> <spam|abuse|ad> [reason]"
            )
        category: Literal["spam", "abuse", "ad"] = tokens[1].lower()  # type: ignore[assignment]
        member = tokens[0].lstrip("@")
        res = await warn_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            category=category,
            reason=" ".join(tokens[2:]) or "manual warning",
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    mute_cmd = on_command("mute", priority=1, block=True)

    @mute_cmd.handle()
    async def _on_mute(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(gateway, event, matcher, runtime, command_name="mute"):
            return
        tokens = _split_args(arg)
        if len(tokens) < 2:
            await matcher.finish("Usage: /mute <member_openid> <10m|1h|600> [reason]")
        member = tokens[0].lstrip("@")
        res = await mute_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            duration=tokens[1],
            reason=" ".join(tokens[2:]) or "manual mute",
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    unmute_cmd = on_command("unmute", priority=1, block=True)

    @unmute_cmd.handle()
    async def _on_unmute(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="unmute"
        ):
            return
        tokens = _split_args(arg)
        if not tokens:
            await matcher.finish("Usage: /unmute <member_openid>")
        member = tokens[0].lstrip("@")
        res = await unmute_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    kick_cmd = on_command("kick", priority=1, block=True)

    @kick_cmd.handle()
    async def _on_kick(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(gateway, event, matcher, runtime, command_name="kick"):
            return
        tokens = _split_args(arg)
        if not tokens:
            await matcher.finish("Usage: /kick <member_openid> [--ban] [reason]")
        member = tokens[0].lstrip("@")
        rest = tokens[1:]
        add_bl = "--ban" in rest
        reason_tokens = [t for t in rest if t != "--ban"]
        res = await kick_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            reason=" ".join(reason_tokens) or "manual kick",
            add_to_blacklist=add_bl,
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    ban_cmd = on_command("ban", priority=1, block=True)

    @ban_cmd.handle()
    async def _on_ban(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(gateway, event, matcher, runtime, command_name="ban"):
            return
        tokens = _split_args(arg)
        if not tokens:
            await matcher.finish("Usage: /ban <member_openid> [reason]")
        member = tokens[0].lstrip("@")
        res = await ban_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            reason=" ".join(tokens[1:]) or "manual blacklist",
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    unban_cmd = on_command("unban", priority=1, block=True)

    @unban_cmd.handle()
    async def _on_unban(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(gateway, event, matcher, runtime, command_name="unban"):
            return
        tokens = _split_args(arg)
        if not tokens:
            await matcher.finish("Usage: /unban <member_openid>")
        member = tokens[0].lstrip("@")
        res = await unban_member(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    recall_cmd = on_command("recall", priority=1, block=True)

    @recall_cmd.handle()
    async def _on_recall(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="recall"
        ):
            return
        tokens = _split_args(arg)
        if not tokens:
            await matcher.finish("Usage: /recall <message_id>")
        res = await recall_message(
            gateway,
            runtime,
            group_openid=event.group_openid,
            message_id=tokens[0],
            operator_openid=event.get_user_id(),
        )
        await _finish_action(gateway, event, matcher, runtime, res)

    approve_cmd = on_command("approve", priority=1, block=True)

    @approve_cmd.handle()
    async def _on_approve(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="approve"
        ):
            return
        tokens = _split_args(arg)
        if len(tokens) < 2:
            await matcher.finish("Usage: /approve <member_openid> <join_request_id>")
        member = tokens[0].lstrip("@")
        res = await approve_join(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            join_request_id=tokens[1],
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    reject_cmd = on_command("reject", priority=1, block=True)

    @reject_cmd.handle()
    async def _on_reject(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="reject"
        ):
            return
        tokens = _split_args(arg)
        if len(tokens) < 2:
            await matcher.finish(
                "Usage: /reject <member_openid> <join_request_id> [reason]"
            )
        member = tokens[0].lstrip("@")
        res = await reject_join(
            gateway,
            runtime,
            group_openid=event.group_openid,
            member_openid=member,
            join_request_id=tokens[1],
            reason=" ".join(tokens[2:]) or "rejected by admin",
            operator_openid=event.get_user_id(),
        )
        await _finish_action(
            gateway, event, matcher, runtime, res, target_openid=member
        )

    shutlist_cmd = on_command("shutlist", priority=1, block=True)

    @shutlist_cmd.handle()
    async def _on_shutlist(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="shutlist"
        ):
            return
        setting = await gateway.get_group_mute_setting(event.group_openid)
        if not setting.members:
            await matcher.finish(
                render_fallback_message(
                    runtime.prompts, "shutlist_empty", mode=setting.global_rule.mode
                )
            )
        lines = [f"Muted ({len(setting.members)}, global={setting.global_rule.mode}):"]
        for m in setting.members[:25]:
            lines.append(f"- {m.member_openid} until {m.mute_expire_at}")
        await matcher.finish("\n".join(lines))

    blacklist_cmd = on_command("blacklist", priority=1, block=True)

    @blacklist_cmd.handle()
    async def _on_blacklist(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="blacklist"
        ):
            return
        res = await gateway.get_group_member_blacklist(event.group_openid)
        if not res.users:
            await matcher.finish(
                render_fallback_message(runtime.prompts, "blacklist_empty")
            )
        lines = [f"Blacklist ({len(res.users)}):"]
        for u in res.users[:25]:
            lines.append(f"- {u.member_openid} banned_at={u.banned_at}")
        await matcher.finish("\n".join(lines))

    requests_cmd = on_command("requests", priority=1, block=True)

    @requests_cmd.handle()
    async def _on_requests(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="requests"
        ):
            return
        res = await gateway.get_group_join_request_list(event.group_openid)
        if not res.list:
            await matcher.finish(
                render_fallback_message(runtime.prompts, "requests_empty")
            )
        lines = [f"Pending join requests ({len(res.list)}):"]
        for r in res.list[:20]:
            risk = f" risk={r.risk_tips}" if r.risk_tips else ""
            lines.append(f"- id={r.join_request_id} member={r.member_openid}{risk}")
        await matcher.finish("\n".join(lines))

    member_cmd = on_command("member", priority=1, block=True)

    @member_cmd.handle()
    async def _on_member(
        gateway: Gateway,
        event: GroupMessageEvent,
        matcher: Matcher,
        arg: Message = CommandArg(),
    ) -> None:
        if not await _authorize(
            gateway, event, matcher, runtime, command_name="member"
        ):
            return
        tokens = _split_args(arg)
        target = tokens[0].lstrip("@") if tokens else event.get_user_id()
        role = await refresh_member_role(
            gateway,
            runtime.config,
            runtime.state,
            event.group_openid,
            target,
            force=True,
        )
        info = await gateway.get_group_member(event.group_openid, target)
        runtime.state.mark_member_checked(event.group_openid, target)
        await matcher.finish(
            f"member={info.member_openid}\n"
            f"role={role}\n"
            f"bot={info.bot}\n"
            f"joined_at={info.joined_at}"
        )


__all__ = ["handle_admin_console", "register_commands"]
