"""Direct OpsMesh group lifecycle entries: join requests, member & bot join/leave."""

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

from qq_admin.manager import MANAGER
from qq_admin.models import ReplySpec
from qq_admin.modules import (
    APPROVAL,
    AUDIT,
    IDENTITY,
    MODERATION,
    SAFEGUARD,
    WARNING,
    AuditRecord,
)
from qq_admin.prompts import notice

group_notice = on_notice(priority=5, block=False)


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


def _audit_lifecycle(group_id: str, action: str, member_id: str) -> None:
    AUDIT.record(
        AuditRecord(
            group_id=group_id,
            action=action,
            target_id=member_id,
            operator_id="platform",
            reason=action,
            succeeded=True,
        )
    )


async def process_group_event(gateway: Gateway, event: GroupNoticeEvent) -> str | None:
    """Route one group notice; bot join/leave always run, others require group on."""
    group_id = event.group_openid
    if not group_id:
        return None
    if isinstance(event, GroupAddRobotEvent):
        await IDENTITY.bot_role(gateway, group_id, force=True)
        return None
    if isinstance(event, GroupDelRobotEvent):
        IDENTITY.forget_group(group_id)
        AUDIT.forget_group(group_id)
        return None
    if not MANAGER.is_group_enabled(group_id):
        return None

    if isinstance(event, GroupJoinRequestEvent) and not event.auto_approved:
        await APPROVAL.review(gateway, group_id, _join_request_from(event))
        return None
    if isinstance(event, GroupMemberAddEvent):
        member_id = event.member_openid
        IDENTITY.forget_member(group_id, member_id)
        _audit_lifecycle(group_id, "member_join", member_id)
        if not MODERATION.config(group_id).welcome_new_members:
            return None
        return await MANAGER.reply_agent.execute(
            ReplySpec(
                group_id=group_id,
                bot_role=await IDENTITY.bot_role(gateway, group_id),
                scenario="member_welcome",
                target_id=member_id,
                fallback=notice("member_welcome", member_id=member_id),
            )
        )
    if isinstance(event, GroupMemberRemoveEvent):
        member_id = event.member_openid
        IDENTITY.forget_member(group_id, member_id)
        WARNING.clear_member(group_id, member_id)
        SAFEGUARD.clear_member(group_id, member_id)
        _audit_lifecycle(group_id, "member_leave", member_id)
    return None


@group_notice.handle()
async def handle_group_event(gateway: Gateway, event: GroupNoticeEvent) -> None:
    reply = await process_group_event(gateway, event)
    if reply:
        await gateway.send(event, reply)


__all__ = ["group_notice", "handle_group_event", "process_group_event"]
