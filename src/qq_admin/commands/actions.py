"""Direct OpsMesh moderation action commands."""

from opsmesh import on_command
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.modules import APPROVAL, MODERATION, WarningCategory

from .helpers import command_args, finish_outcome, require_admin

warn_cmd = on_command("warn", priority=1, block=True)
mute_cmd = on_command("mute", priority=1, block=True)
unmute_cmd = on_command("unmute", priority=1, block=True)
kick_cmd = on_command("kick", priority=1, block=True)
ban_cmd = on_command("ban", priority=1, block=True)
unban_cmd = on_command("unban", priority=1, block=True)
recall_cmd = on_command("recall", priority=1, block=True)
approve_cmd = on_command("approve", priority=1, block=True)
reject_cmd = on_command("reject", priority=1, block=True)


@warn_cmd.handle()
async def handle_warn(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "warn")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /warn <member> [spam|abuse|ad] [reason]")
    member = args[0].lstrip("@")
    category: WarningCategory = "spam"
    reason_tokens = args[1:]
    if reason_tokens and reason_tokens[0].lower() in {"spam", "abuse", "ad"}:
        raw_cat = reason_tokens[0].lower()
        category = (
            "ad" if raw_cat == "ad" else ("abuse" if raw_cat == "abuse" else "spam")
        )
        reason_tokens = reason_tokens[1:]
    outcome = await MODERATION.warn(
        gateway,
        event.group_openid,
        member,
        category=category,
        reason=" ".join(reason_tokens) or "manual warning",
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@mute_cmd.handle()
async def handle_mute(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "mute")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /mute <member> [10m|2h|1d] [reason]")
    member = args[0].lstrip("@")
    duration = args[1] if len(args) >= 2 else "10m"
    reason = " ".join(args[2:]) or "manual mute"
    outcome = await MODERATION.mute(
        gateway,
        event.group_openid,
        member,
        duration=duration,
        reason=reason,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@unmute_cmd.handle()
async def handle_unmute(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "unmute")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /unmute <member>")
    member = args[0].lstrip("@")
    outcome = await MODERATION.unmute(
        gateway, event.group_openid, member, operator_id=event.get_user_id()
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@kick_cmd.handle()
async def handle_kick(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "kick")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /kick <member> [reason]")
    member = args[0].lstrip("@")
    reason = " ".join(args[1:]) or "manual kick"
    outcome = await MODERATION.kick(
        gateway,
        event.group_openid,
        member,
        reason=reason,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@ban_cmd.handle()
async def handle_ban(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "ban")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /ban <member> [reason]")
    member = args[0].lstrip("@")
    reason = " ".join(args[1:]) or "manual ban"
    outcome = await MODERATION.ban(
        gateway,
        event.group_openid,
        member,
        reason=reason,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@unban_cmd.handle()
async def handle_unban(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "unban")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /unban <member>")
    member = args[0].lstrip("@")
    outcome = await MODERATION.unban(
        gateway, event.group_openid, member, operator_id=event.get_user_id()
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@recall_cmd.handle()
async def handle_recall(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "recall")
    args = command_args(event)
    ref = event.message_reference
    message_id = args[0] if args else (ref.message_id if ref else "")
    if not message_id:
        await matcher.finish("Usage: /recall <message_id> (or reply to target message)")
    reason = " ".join(args[1:]) or "manual recall"
    outcome = await MODERATION.recall(
        gateway,
        event.group_openid,
        message_id,
        reason=reason,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=message_id)


@approve_cmd.handle()
async def handle_approve(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "approve")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /approve <member> [join_request_id]")
    member = args[0].lstrip("@")
    request_id = args[1] if len(args) >= 2 else None
    outcome = await APPROVAL.approve(
        gateway,
        event.group_openid,
        member,
        request_id=request_id,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)


@reject_cmd.handle()
async def handle_reject(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    await require_admin(gateway, event, matcher, "reject")
    args = command_args(event)
    if not args:
        await matcher.finish("Usage: /reject <member> [reason]")
    member = args[0].lstrip("@")
    reason = " ".join(args[1:]) or "manual reject"
    outcome = await APPROVAL.reject(
        gateway,
        event.group_openid,
        member,
        reason=reason,
        operator_id=event.get_user_id(),
    )
    await finish_outcome(gateway, event, matcher, outcome, target_id=member)
