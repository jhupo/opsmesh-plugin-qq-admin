"""JoinApprover: automatic and manual Official QQ v2 join-request handling."""

from datetime import UTC, datetime
from typing import Literal

from opsmesh.log import logger
from qq import Gateway, JoinRequest

from qq_admin.config import AdminConfig
from qq_admin.jev import JevEvaluator
from qq_admin.resources import PromptCatalog
from qq_admin.state import GroupStateStore

from .moderator import ActionOutcome
from .policy import SafeguardPolicy


class JoinApprover:
    """Approves or rejects group join requests via risk_tips + Jev assessment."""

    def __init__(
        self,
        config: AdminConfig,
        state: GroupStateStore,
        policy: SafeguardPolicy,
        jev: JevEvaluator,
        catalog: PromptCatalog,
    ) -> None:
        self.config = config
        self.state = state
        self.policy = policy
        self.jev = jev
        self.catalog = catalog

    async def approve(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        request_id: str,
        *,
        reason: str = "approved",
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Approve a pending join request."""
        async with self.state.lock:
            try:
                await gateway.approval_join_request(
                    group_id,
                    member_id,
                    op="approve",
                    join_request_id=request_id,
                )
            except Exception as exc:
                return ActionOutcome(
                    succeeded=False,
                    action="approve",
                    message=self.catalog.format_fallback(
                        "action_failed", reason=str(exc)
                    ),
                )
            self.state.increment_daily(group_id, "approve")
            self.state.record_audit(
                group_id=group_id,
                action="approve",
                target_id=member_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="approve",
                message=self.catalog.format_fallback(
                    "approve_done", request_id=request_id, member_id=member_id
                ),
            )

    async def reject(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        request_id: str,
        *,
        reason: str = "rejected",
        blacklist: bool = False,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        """Decline a pending join request."""
        async with self.state.lock:
            try:
                await gateway.approval_join_request(
                    group_id,
                    member_id,
                    op="decline",
                    join_request_id=request_id,
                    reject_reason=reason,
                    add_to_member_blacklist=blacklist,
                )
            except Exception as exc:
                return ActionOutcome(
                    succeeded=False,
                    action="reject",
                    message=self.catalog.format_fallback(
                        "action_failed", reason=str(exc)
                    ),
                )
            self.state.increment_daily(group_id, "reject")
            self.state.record_audit(
                group_id=group_id,
                action="reject",
                target_id=member_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=True,
            )
            return ActionOutcome(
                succeeded=True,
                action="reject",
                message=self.catalog.format_fallback(
                    "reject_done",
                    request_id=request_id,
                    member_id=member_id,
                    reason=reason,
                ),
            )

    def _group_policy(
        self, group_id: str
    ) -> tuple[bool, Literal["ignore", "approve", "reject"], int, int]:
        ap = self.config.approval
        for item in ap.groups:
            if item.group_id == group_id:
                return (
                    True,
                    item.default_action,
                    item.daily_approve_limit or ap.daily_approve_limit,
                    item.daily_reject_limit or ap.daily_reject_limit,
                )
        return (
            ap.enabled,
            ap.default_action,
            ap.daily_approve_limit,
            ap.daily_reject_limit,
        )

    @staticmethod
    def _extract_verify_payload(
        req: JoinRequest,
    ) -> tuple[str, list[dict[str, str]]]:
        texts: list[str] = []
        pairs: list[dict[str, str]] = []
        if req.verify_info is not None:
            if req.verify_info.verify_message:
                texts.append(req.verify_info.verify_message)
            for qa in req.verify_info.review_qa_list or []:
                pairs.append({"question": qa.question, "answer": qa.answer})
                if qa.answer:
                    texts.append(qa.answer)
        return "\n".join(texts), pairs

    @staticmethod
    def _is_stale(req: JoinRequest, max_age_seconds: int) -> bool:
        if req.apply_at is None:
            return False
        now = datetime.now(UTC)
        if isinstance(req.apply_at, datetime):
            ts = (
                req.apply_at
                if req.apply_at.tzinfo
                else req.apply_at.replace(tzinfo=UTC)
            )
        else:
            try:
                raw = str(req.apply_at).replace("Z", "+00:00")
                ts = datetime.fromisoformat(raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except ValueError:
                return False
        return (now - ts).total_seconds() > max_age_seconds

    async def review_request(
        self, gateway: Gateway, group_id: str, req: JoinRequest
    ) -> ActionOutcome | None:
        """Evaluate a single JoinRequest via platform risk_tips + JevEvaluator."""
        ap = self.config.approval
        enabled, default_action, appr_limit, rej_limit = self._group_policy(group_id)
        if not enabled or not req.join_request_id or not req.member_openid:
            return None
        if self._is_stale(req, ap.max_pending_seconds):
            return None

        bot_role = await self.policy.bot_role(gateway, group_id)
        if bot_role not in ("owner", "admin"):
            return None
        is_owner = bot_role == "owner"

        verify_text, qa_pairs = self._extract_verify_payload(req)
        decision = default_action
        reason = self.catalog.format_fallback("auto_approve_reason")

        if ap.reject_on_risk_tips and req.risk_tips:
            decision = "reject"
            reason = self.catalog.format_fallback("auto_reject_risk")
        elif ap.use_jev_review and self.jev.is_active:
            risk = await self.jev.assess_join_request(
                verify_text, qa_pairs, risk_tips=req.risk_tips
            )
            if (
                risk.status == "ok"
                and risk.risk_probability >= self.config.jev.join_reject_threshold
            ):
                decision = "reject"
                reason = self.catalog.format_fallback("auto_reject_jev")

        if decision == "approve":
            if (
                not is_owner
                and self.state.daily_count(group_id, "approve") >= appr_limit
            ):
                return None
            return await self.approve(
                gateway,
                group_id,
                req.member_openid,
                req.join_request_id,
                reason=reason,
            )
        if decision == "reject":
            if not is_owner and self.state.daily_count(group_id, "reject") >= rej_limit:
                return None
            return await self.reject(
                gateway,
                group_id,
                req.member_openid,
                req.join_request_id,
                reason=reason,
            )
        return None

    async def poll_all_groups(self, gateway: Gateway) -> list[ActionOutcome]:
        """Poll pending join requests across all active groups once."""
        ap = self.config.approval
        targets: set[str] = set()
        if ap.enabled:
            targets.update(self.config.moderation.enabled_groups)
        override_ids = {g.group_id for g in ap.groups if g.group_id}
        targets.update(override_ids)

        outcomes: list[ActionOutcome] = []
        for group_id in sorted(targets):
            if group_id not in override_ids and not self.policy.is_group_active(
                group_id
            ):
                continue
            try:
                page = await gateway.get_group_join_request_list(group_id)
            except Exception as exc:
                logger.warning(f"qq_admin join poll failed for {group_id}: {exc}")
                continue
            for req in page.list:
                res = await self.review_request(gateway, group_id, req)
                if res is not None:
                    outcomes.append(res)
        return outcomes


__all__ = ["JoinApprover"]
