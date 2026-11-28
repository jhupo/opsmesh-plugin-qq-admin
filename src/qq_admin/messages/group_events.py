"""Group lifecycle entries: join requests, member join/leave, bot join/leave."""

from opsmesh import on_notice
from qq import (
    Gateway,
    GroupAddRobotEvent,
    GroupDelRobotEvent,
    GroupJoinRequestEvent,
    GroupMemberAddEvent,
    GroupMemberRemoveEvent,
    GroupNoticeEvent,
    JoinRequest,
    VerifyInfo,
)

from qq_admin.manager import ServiceManager
from qq_admin.models import ReplySpec
from qq_admin.modules import AuditRecord


def _join_request_from(event: GroupJoinRequestEvent) -> JoinRequest:
    verify = (
        event.verify_info
        if isinstance(event.verify_info, VerifyInfo)
        else VerifyInfo(verify_message=str(event.verify_info or ""))
    )
    return JoinRequest(
        join_request_id=event.join_request_id,
        member_openid=event.member_openid,
        username=event.username,
        apply_source=event.apply_source,
        invited_by=event.invited_by,
        risk_tips=event.risk_tips,
        verify_info=verify,
    )


def _audit_lifecycle(
    manager: ServiceManager, group_id: str, action: str, member_id: str
) -> None:
    manager.audit.record(
        AuditRecord(
            group_id=group_id,
            action=action,
            target_id=member_id,
            operator_id="platform",
            reason=action,
            succeeded=True,
        )
    )


async def on_join_request(
    gateway: Gateway, event: GroupJoinRequestEvent, manager: ServiceManager
) -> None:
    if event.auto_approved:
        return
    await manager.approval.review(
        gateway, event.group_openid, _join_request_from(event)
    )


async def on_member_join(
    gateway: Gateway, event: GroupMemberAddEvent, manager: ServiceManager
) -> str | None:
    group_id, member_id = event.group_openid, event.member_openid
    manager.identity.forget_member(group_id, member_id)
    _audit_lifecycle(manager, group_id, "member_join", member_id)
    if not manager.moderation.config(group_id).welcome_new_members:
        return None
    return await manager.reply_agent.execute(
        ReplySpec(
            manager=manager,
            group_id=group_id,
            bot_role=await manager.identity.bot_role(gateway, group_id),
            scenario="member_welcome",
            target_id=member_id,
            fallback=manager.catalog.format_fallback(
                "member_welcome", member_id=member_id
            ),
        )
    )


async def on_member_leave(
    event: GroupMemberRemoveEvent, manager: ServiceManager
) -> None:
    group_id, member_id = event.group_openid, event.member_openid
    manager.identity.forget_member(group_id, member_id)
    manager.warning.clear_member(group_id, member_id)
    manager.safeguard.clear_member(group_id, member_id)
    _audit_lifecycle(manager, group_id, "member_leave", member_id)


async def on_bot_join(
    gateway: Gateway, event: GroupAddRobotEvent, manager: ServiceManager
) -> None:
    await manager.identity.bot_role(gateway, event.group_openid, force=True)


async def on_bot_leave(event: GroupDelRobotEvent, manager: ServiceManager) -> None:
    group_id = event.group_openid
    manager.identity.forget_group(group_id)
    manager.moderation.forget_group(group_id)
    manager.audit.forget_group(group_id)
    await manager.reset_group_sessions(group_id)


async def handle_group_event(
    gateway: Gateway, event: GroupNoticeEvent, manager: ServiceManager
) -> str | None:
    """Route one group notice; bot join/leave always run, others need the group on."""
    group_id = event.group_openid
    if not group_id:
        return None
    if isinstance(event, GroupAddRobotEvent):
        await on_bot_join(gateway, event, manager)
        return None
    if isinstance(event, GroupDelRobotEvent):
        await on_bot_leave(event, manager)
        return None
    if not manager.is_group_enabled(group_id):
        return None
    if isinstance(event, GroupJoinRequestEvent):
        await on_join_request(gateway, event, manager)
    elif isinstance(event, GroupMemberAddEvent):
        return await on_member_join(gateway, event, manager)
    elif isinstance(event, GroupMemberRemoveEvent):
        await on_member_leave(event, manager)
    return None


def bind_group_events(manager: ServiceManager) -> None:
    @on_notice(priority=5, block=False).handle()
    async def _group_event(gateway: Gateway, event: GroupNoticeEvent) -> None:
        reply = await handle_group_event(gateway, event, manager)
        if reply:
            await gateway.send(event, reply)


__all__ = ["bind_group_events", "handle_group_event"]
