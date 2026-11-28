"""EventRouter: automatic group moderation pipeline and OpsMesh lifecycle hooks."""

from opsmesh import get_driver, on_message, on_notice
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

from .agents import DecisionOutcome, ReplySpec, TurnContext
from .jev import MessageAssessment
from .runtime import AdminRuntime


class EventRouter:
    """Routes inbound QQ group events through JevEvaluator -> Planner -> Composer."""

    def __init__(self, runtime: AdminRuntime) -> None:
        self.runtime = runtime

    async def handle_message(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        *,
        matcher: Matcher | None = None,
    ) -> bool:
        """Moderate one inbound group message; returns False silently on safe chat."""
        cfg = self.runtime.config
        if not cfg.plugin.enabled or not cfg.moderation.enabled:
            return False

        group_id = event.group_openid
        member_id = event.get_user_id()
        if (
            not group_id
            or not member_id
            or not self.runtime.policy.is_group_active(group_id)
        ):
            return False

        text = event.get_plaintext().strip() or (event.content or "").strip()
        if text.startswith("/"):
            return False

        bot_role = await self.runtime.policy.bot_role(gateway, group_id)
        sender_role = await self.runtime.policy.member_role(
            gateway, group_id, member_id, throttle=True
        )
        self.runtime.state.append_message(group_id, event.id, member_id, text)

        if await self._should_route_admin_mention(
            gateway, event, group_id, member_id, text
        ):
            return await self._handle_admin_instruction(
                gateway,
                event,
                group_id=group_id,
                member_id=member_id,
                text=text,
                bot_role=bot_role,
                sender_role=sender_role,
                matcher=matcher,
            )

        return await self._moderate_member_message(
            gateway,
            event,
            group_id=group_id,
            member_id=member_id,
            text=text,
            bot_role=bot_role,
            sender_role=sender_role,
            matcher=matcher,
        )

    async def _should_route_admin_mention(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        group_id: str,
        member_id: str,
        text: str,
    ) -> bool:
        cfg = self.runtime.config
        if not (
            cfg.moderation.allow_admin_nl_control
            and cfg.agent.enabled
            and event.is_tome()
            and text
        ):
            return False
        allowed, _ = await self.runtime.policy.authorize(
            gateway, group_id, member_id, minimum_role="admin"
        )
        return allowed

    async def _handle_admin_instruction(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        *,
        group_id: str,
        member_id: str,
        text: str,
        bot_role: str,
        sender_role: str,
        matcher: Matcher | None,
    ) -> bool:
        turn = TurnContext(
            gateway=gateway,
            runtime=self.runtime,
            group_id=group_id,
            member_id=member_id,
            message_id=event.id,
            text=text,
            bot_role=bot_role,
            sender_role=sender_role,
            mode="admin_command",
        )
        outcome = await self.runtime.planner.execute(turn)
        if outcome.should_reply:
            await self._send_composed_reply(
                gateway,
                event,
                outcome=outcome,
                turn=turn,
                facts={"instruction": text, "tool_outputs": list(turn.tool_outputs)},
            )
            if matcher is not None and outcome.action_taken:
                matcher.stop_propagation()
            return True
        return outcome.action_taken

    async def _moderate_member_message(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        *,
        group_id: str,
        member_id: str,
        text: str,
        bot_role: str,
        sender_role: str,
        matcher: Matcher | None,
    ) -> bool:
        if not self.runtime.jev.is_active:
            return False

        images = await self._download_images(gateway, event)
        assessment = await self.runtime.jev.assess_message(
            group_id,
            member_id,
            text,
            recent_messages=self.runtime.state.recent_context(group_id),
            images=images or None,
        )
        if assessment.status != "ok":
            return False
        if (
            assessment.injection_probability
            >= self.runtime.config.jev.injection_block_threshold
        ):
            logger.warning(
                f"qq_admin blocked prompt injection from {member_id} in {group_id}"
            )
            return False

        tier = assessment.enforcement_tier(self.runtime.config.jev)
        if tier == "none":
            return False

        if self.runtime.config.agent.enabled:
            return await self._execute_agent_moderation(
                gateway,
                event,
                group_id=group_id,
                member_id=member_id,
                text=text,
                bot_role=bot_role,
                sender_role=sender_role,
                assessment=assessment,
                tier=tier,
                matcher=matcher,
            )

        results = await self.runtime.moderator.apply_ladder(
            gateway,
            group_id,
            member_id,
            message_id=event.id,
            category=assessment.warning_category,
            tier=tier,
            reason=assessment.primary_violation,
        )
        notices = [r.message for r in results if r.succeeded and r.message]
        if notices:
            await gateway.send(event, "\n".join(notices))
            if matcher is not None and self.runtime.config.moderation.stop_on_violation:
                matcher.stop_propagation()
            return True
        return False

    async def _execute_agent_moderation(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        *,
        group_id: str,
        member_id: str,
        text: str,
        bot_role: str,
        sender_role: str,
        assessment: MessageAssessment,
        tier: str,
        matcher: Matcher | None,
    ) -> bool:
        turn = TurnContext(
            gateway=gateway,
            runtime=self.runtime,
            group_id=group_id,
            member_id=member_id,
            message_id=event.id,
            text=text,
            bot_role=bot_role,
            sender_role=sender_role,
            mode="auto_moderate",
            assessment=assessment,
        )
        outcome = await self.runtime.planner.execute(turn)
        if outcome.should_reply:
            await self._send_composed_reply(
                gateway,
                event,
                outcome=outcome,
                turn=turn,
                facts={
                    "violation": assessment.primary_violation,
                    "severity": assessment.severity,
                    "tier": tier,
                    "tool_outputs": list(turn.tool_outputs),
                },
            )
        if outcome.action_taken and self.runtime.config.moderation.stop_on_violation:
            if matcher is not None:
                matcher.stop_propagation()
        return outcome.action_taken

    async def _send_composed_reply(
        self,
        gateway: Gateway,
        event: GroupMessageEvent,
        *,
        outcome: DecisionOutcome,
        turn: TurnContext,
        facts: dict[str, object],
    ) -> None:
        fallback = "; ".join(turn.tool_outputs) or outcome.summary
        reply = await self.runtime.composer.compose(
            ReplySpec(
                runtime=self.runtime,
                group_id=turn.group_id,
                bot_role=turn.bot_role,
                scenario=outcome.scenario,
                actor_id=turn.member_id,
                actor_role=turn.sender_role,
                target_id=outcome.target_id or turn.member_id,
                executed_actions=outcome.executed_actions,
                facts={**facts, "summary": outcome.summary},
                fallback=fallback,
            )
        )
        if reply:
            await gateway.send(event, reply)

    async def _download_images(
        self, gateway: Gateway, event: GroupMessageEvent
    ) -> list[bytes]:
        jev_cfg = self.runtime.config.jev
        if not jev_cfg.enable_image_review or not event.attachments:
            return []
        images: list[bytes] = []
        for att in event.attachments[: jev_cfg.max_images]:
            ctype = (att.content_type or "").lower()
            if not att.url or (ctype and not ctype.startswith("image/")):
                continue
            try:
                images.append(await gateway.download_attachment(att.url))
            except Exception as exc:
                logger.debug(f"qq_admin skipped image download: {exc}")
        return images

    async def handle_notice(self, gateway: Gateway, event: GroupNoticeEvent) -> None:
        """Handle bot group-add and join-request notice events."""
        if not self.runtime.config.plugin.enabled:
            return
        if isinstance(event, GroupAddRobotEvent) and event.group_openid:
            await self.runtime.policy.bot_role(gateway, event.group_openid, force=True)
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
            await self.runtime.approver.review_request(gateway, event.group_openid, req)


def bind_events(runtime: AdminRuntime) -> EventRouter:
    """Register EventRouter handlers and startup/shutdown hooks on OpsMesh."""
    router = EventRouter(runtime)
    msg_matcher = on_message(priority=5, block=False)

    @msg_matcher.handle()
    async def _on_message(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        await router.handle_message(gateway, event, matcher=matcher)

    notice_matcher = on_notice(priority=5, block=False)

    @notice_matcher.handle()
    async def _on_notice(gateway: Gateway, event: GroupNoticeEvent) -> None:
        await router.handle_notice(gateway, event)

    driver = get_driver()
    driver.on_startup(runtime.startup)
    driver.on_shutdown(runtime.shutdown)
    return router


__all__ = ["EventRouter", "bind_events"]
