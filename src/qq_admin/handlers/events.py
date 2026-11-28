"""OpsMesh automatic event pipeline (Jev -> DecisionAgent -> ReplyAgent) & loops."""

import asyncio

from opsmesh import get_driver, get_gateways, on_message, on_notice
from opsmesh.log import logger
from opsmesh.matcher import Matcher
from qq import (
    Gateway,
    GroupAddRobotEvent,
    GroupJoinRequestEvent,
    GroupMessageEvent,
    GroupNoticeEvent,
    JoinRequest,
    VerifyInfo,
)

from qq_admin.agents import (
    ModerationContext,
    ReplyContext,
    generate_reply,
    run_decision_agent,
)
from qq_admin.jev import evaluate_message
from qq_admin.moderation import (
    enforce_escalation_violation,
    evaluate_and_handle_join_request,
    evaluate_command_permission,
    is_group_enabled,
    refresh_bot_role,
    refresh_member_role,
    scan_join_requests_once,
)
from qq_admin.state import PluginRuntime

_background_tasks: list[asyncio.Task[None]] = []


async def _download_event_images(
    gateway: Gateway, event: GroupMessageEvent, max_images: int
) -> list[bytes]:
    images: list[bytes] = []
    for att in event.attachments[:max_images]:
        ctype = (att.content_type or "").lower()
        if not att.url or (ctype and not ctype.startswith("image/")):
            continue
        try:
            images.append(await gateway.download_attachment(att.url))
        except Exception as exc:
            logger.debug(f"qq_admin skipped attachment download: {exc}")
    return images


async def handle_group_message_event(
    gateway: Gateway,
    event: GroupMessageEvent,
    runtime: PluginRuntime,
    *,
    matcher: Matcher | None = None,
) -> bool:
    """Process one inbound group message through Jev -> DecisionAgent -> ReplyAgent.

    Normal chat messages return False silently without sending any reply.
    """
    cfg = runtime.config
    if not cfg.enabled or not cfg.auto_moderate.enabled:
        return False

    group_openid = event.group_openid
    member_openid = event.get_user_id()
    if not group_openid or not member_openid:
        return False
    if not is_group_enabled(cfg, runtime.state, group_openid):
        return False

    plain_text = event.get_plaintext().strip() or (event.content or "").strip()
    if plain_text.startswith("/"):
        return False

    bot_role = await refresh_bot_role(gateway, cfg, runtime.state, group_openid)
    sender_role = await refresh_member_role(
        gateway,
        cfg,
        runtime.state,
        group_openid,
        member_openid,
        throttle_sender=True,
    )
    runtime.state.record_message(group_openid, event.id, member_openid, plain_text)

    # Branch A: Privileged admin/owner natural-language control when @mentioning bot.
    if (
        cfg.auto_moderate.allow_admin_nl_control
        and cfg.llm.enabled
        and event.is_tome()
        and plain_text
    ):
        allowed, _ = await evaluate_command_permission(
            gateway,
            cfg,
            runtime.state,
            group_openid,
            member_openid,
            minimum_role="admin",
        )
        if allowed:
            mctx = ModerationContext(
                gateway=gateway,
                runtime=runtime,
                group_openid=group_openid,
                member_openid=member_openid,
                message_id=event.id,
                plain_text=plain_text,
                bot_role=bot_role,
                sender_role=sender_role,
                mode="admin_command",
            )
            report = await run_decision_agent(mctx)
            if report.should_reply:
                reply_text = await generate_reply(
                    ReplyContext(
                        runtime=runtime,
                        group_openid=group_openid,
                        bot_role=bot_role,
                        scenario=report.scenario,
                        actor_openid=member_openid,
                        actor_role=sender_role,
                        target_openid=report.target_openid,
                        executed_actions=report.executed_actions,
                        facts={
                            "instruction": plain_text,
                            "facts_summary": report.facts_summary,
                            "tool_results": list(mctx.tool_results),
                        },
                        fallback_text=report.facts_summary,
                    )
                )
                if reply_text:
                    await gateway.send(event, reply_text)
                if matcher is not None and report.action_taken:
                    matcher.stop_propagation()
                return True
            return report.action_taken

    # Branch B: Pure Jev-driven violation detection (zero brittle regex/burst rules).
    if not runtime.jev_client.is_ready:
        return False

    images: list[bytes] = []
    if cfg.jev.enable_image_review and event.attachments:
        images = await _download_event_images(gateway, event, cfg.jev.max_images)

    jev_eval = await evaluate_message(
        runtime.jev_client,
        runtime.prompts,
        text=plain_text,
        group_openid=group_openid,
        member_openid=member_openid,
        recent_messages=runtime.state.get_recent_messages(group_openid, limit=8),
        image_bytes_list=images or None,
    )
    if jev_eval.status != "ok":
        return False
    if jev_eval.is_prompt_injection_prob >= cfg.jev.injection_block_threshold:
        logger.warning(
            f"qq_admin blocked suspected prompt injection from {member_openid} "
            f"in {group_openid}"
        )
        return False

    tier = jev_eval.moderation_tier(cfg.jev)
    if tier == "none":
        return False

    if cfg.llm.enabled:
        mctx = ModerationContext(
            gateway=gateway,
            runtime=runtime,
            group_openid=group_openid,
            member_openid=member_openid,
            message_id=event.id,
            plain_text=plain_text,
            bot_role=bot_role,
            sender_role=sender_role,
            mode="auto_moderate",
            evaluation=jev_eval,
        )
        report = await run_decision_agent(mctx)
        if report.should_reply:
            fallback = "; ".join(mctx.tool_results) or report.facts_summary
            reply_text = await generate_reply(
                ReplyContext(
                    runtime=runtime,
                    group_openid=group_openid,
                    bot_role=bot_role,
                    scenario=report.scenario,
                    actor_openid=member_openid,
                    actor_role=sender_role,
                    target_openid=report.target_openid or member_openid,
                    executed_actions=report.executed_actions,
                    facts={
                        "violation": jev_eval.primary_violation,
                        "severity": jev_eval.violation_severity,
                        "tier": tier,
                        "facts_summary": report.facts_summary,
                        "tool_results": list(mctx.tool_results),
                    },
                    fallback_text=fallback,
                )
            )
            if reply_text:
                await gateway.send(event, reply_text)
        if report.action_taken and cfg.auto_moderate.stop_on_violation:
            if matcher is not None:
                matcher.stop_propagation()
        return report.action_taken

    outcomes = await enforce_escalation_violation(
        gateway,
        runtime,
        group_openid=group_openid,
        member_openid=member_openid,
        message_id=event.id,
        category=jev_eval.warning_category,
        severity=tier,
        reason=jev_eval.primary_violation,
    )
    notices = [r.summary for r in outcomes if r.ok and r.summary]
    if notices:
        await gateway.send(event, "\n".join(notices))
        if matcher is not None and cfg.auto_moderate.stop_on_violation:
            matcher.stop_propagation()
        return True
    return False


async def handle_group_notice_event(
    gateway: Gateway, event: GroupNoticeEvent, runtime: PluginRuntime
) -> None:
    """Handle GroupAddRobotEvent and GroupJoinRequestEvent automatically."""
    if not runtime.config.enabled:
        return
    if isinstance(event, GroupAddRobotEvent) and event.group_openid:
        await refresh_bot_role(
            gateway, runtime.config, runtime.state, event.group_openid, force=True
        )
        return
    if isinstance(event, GroupJoinRequestEvent) and event.group_openid:
        verify = (
            event.verify_info
            if isinstance(event.verify_info, VerifyInfo)
            else VerifyInfo(verify_message=str(event.verify_info or ""))
        )
        req = JoinRequest(
            join_request_id=event.join_request_id,
            member_openid=event.member_openid,
            username=event.username,
            apply_source=event.apply_source,
            invited_by=event.invited_by,
            risk_tips=event.risk_tips,
            verify_info=verify,
        )
        await evaluate_and_handle_join_request(
            gateway, runtime, group_openid=event.group_openid, req=req
        )


async def _join_poll_loop(runtime: PluginRuntime) -> None:
    interval = runtime.config.auto_approve.check_interval_seconds
    while interval > 0:
        try:
            await asyncio.sleep(interval)
            for gw in get_gateways().values():
                if isinstance(gw, Gateway):
                    await scan_join_requests_once(gw, runtime)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"qq_admin join poll loop error: {exc}")


async def _cleanup_loop(runtime: PluginRuntime) -> None:
    while True:
        try:
            await asyncio.sleep(600)
            runtime.state.cleanup()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"qq_admin cleanup loop error: {exc}")


def register_event_handlers(runtime: PluginRuntime) -> None:
    """Register OpsMesh event handlers and startup/shutdown lifecycle hooks."""
    msg_matcher = on_message(priority=5, block=False)

    @msg_matcher.handle()
    async def _on_group_message(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        await handle_group_message_event(gateway, event, runtime, matcher=matcher)

    notice_matcher = on_notice(priority=5, block=False)

    @notice_matcher.handle()
    async def _on_group_notice(gateway: Gateway, event: GroupNoticeEvent) -> None:
        await handle_group_notice_event(gateway, event, runtime)

    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        if not runtime.config.enabled:
            return
        await runtime.jev_client.startup()
        if (
            runtime.config.auto_approve.enabled or runtime.config.auto_approve.groups
        ) and runtime.config.auto_approve.check_interval_seconds > 0:
            _background_tasks.append(asyncio.create_task(_join_poll_loop(runtime)))
        _background_tasks.append(asyncio.create_task(_cleanup_loop(runtime)))

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        for task in list(_background_tasks):
            if not task.done():
                task.cancel()
        _background_tasks.clear()
        await runtime.jev_client.shutdown()


__all__ = [
    "handle_group_message_event",
    "handle_group_notice_event",
    "register_event_handlers",
]
