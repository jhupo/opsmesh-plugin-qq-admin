"""Event-driven `GroupJoinRequestEvent` evaluator and pending-list reconciliation."""

from typing import Literal

from qq import Gateway, GroupJoinRequestEvent, JoinRequestItem

from qq_admin.config import QQAdminConfig
from qq_admin.context import AdminContext, OperatorIdentity
from qq_admin.typing import AuditSource, AuditStatus, RoleTier

from .audit import AuditService
from .moderation import ModerationService


class AutoApproveService:
    """Evaluate inbound join requests against keyword, inviter, and risk rules."""

    def __init__(
        self,
        *,
        config: QQAdminConfig,
        moderation: ModerationService,
        audit: AuditService,
    ) -> None:
        self._config = config
        self._moderation = moderation
        self._audit = audit

    def evaluate(
        self,
        *,
        verify_info: str = "",
        risk_tips: str = "",
        invited_by: str | None = None,
        auto_approved: bool = False,
    ) -> Literal["skip", "approve", "decline", "manual"]:
        if not self._config.auto_approve.enabled or auto_approved:
            return "skip"
        if risk_tips and self._config.auto_approve.reject_on_risk_tips:
            return "decline"
        if (
            invited_by
            and invited_by in self._config.auto_approve.trusted_inviter_openids
        ):
            return "approve"
        if self._config.auto_approve.pass_keywords:
            lowered = verify_info.lower()
            if any(
                kw.lower() in lowered for kw in self._config.auto_approve.pass_keywords
            ):
                return "approve"
        return "manual"

    async def handle_event(
        self, gateway: Gateway, event: GroupJoinRequestEvent
    ) -> Literal["skip", "approve", "decline", "manual"]:
        decision = self.evaluate(
            verify_info=event.verify_info,
            risk_tips=event.risk_tips,
            invited_by=event.invited_by,
            auto_approved=event.auto_approved,
        )
        ctx = AdminContext(
            gateway=gateway,
            group_openid=event.group_openid,
            operator=OperatorIdentity(
                openid="system:auto_approve",
                role=RoleTier.SUPERUSER,
                is_superuser=True,
            ),
            source=AuditSource.AUTO,
        )
        if decision == "approve":
            await self._moderation.decide_join_request(
                ctx,
                member_openid=event.member_openid,
                op="approve",
                join_request_id=event.join_request_id or None,
            )
        elif decision == "decline":
            await self._moderation.decide_join_request(
                ctx,
                member_openid=event.member_openid,
                op="decline",
                join_request_id=event.join_request_id or None,
                reject_reason=self._config.auto_approve.reject_reason,
            )
        elif decision == "skip" and event.auto_approved:
            await self._audit.record(
                ctx,
                action="auto_approve_skip",
                status=AuditStatus.SUCCESS,
                target_openid=event.member_openid,
                detail="Already auto-approved by QQ platform; skipped.",
            )
        return decision

    async def reconcile_pending(
        self, gateway: Gateway, group_openid: str
    ) -> list[tuple[JoinRequestItem, str]]:
        """Poll pending join requests and apply auto-approval rules."""
        if not self._config.auto_approve.enabled:
            return []
        res = await gateway.get_group_join_request_list(group_openid)
        results: list[tuple[JoinRequestItem, str]] = []
        for item in res.join_requests:
            ev = GroupJoinRequestEvent(
                group_openid=group_openid,
                join_request_id=item.join_request_id,
                member_openid=item.member_openid,
                username=item.username,
                apply_source=item.apply_source,
                invited_by=item.invited_by,
                verify_info=item.verify_info,
                risk_tips=item.risk_tips,
            )
            decision = await self.handle_event(gateway, ev)
            results.append((item, decision))
        return results


__all__ = ["AutoApproveService"]
