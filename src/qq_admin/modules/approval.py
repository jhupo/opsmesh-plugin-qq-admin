"""Event-driven join-request approval module with self-owned ApprovalConfig."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from qq import Gateway, JoinRequest

from qq_admin.store import ConfigStore, parse_field_value

from .audit import AuditRecord
from .moderation import ActionOutcome

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager


class ApprovalConfig(BaseModel):
    """Automatic join-request review settings."""

    enabled: bool = False
    default_action: Literal["ignore", "approve", "reject"] = "ignore"
    reject_on_risk_tips: bool = True
    use_jev_review: bool = True
    reject_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    daily_approve_limit: int = Field(default=10, ge=1)
    daily_reject_limit: int = Field(default=20, ge=1)


class ApprovalModule:
    """Reviews Official QQ v2 join requests via risk_tips and Jev."""

    def __init__(self, store: ConfigStore, manager: "ServiceManager") -> None:
        self._store = store
        self._manager = manager

    def config(self, group_id: str | None = None) -> ApprovalConfig:
        raw = self._store.load_section("approval", group_id=group_id)
        return ApprovalConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> ApprovalConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(ApprovalConfig, key, raw_value)
        validated = ApprovalConfig.model_validate(current)
        self._store.save_section("approval", validated.model_dump(), group_id=group_id)
        return validated

    async def risk_probability(self, group_id: str, request: JoinRequest) -> float:
        verify = request.verify_info
        qa_pairs = [
            {"question": qa.question, "answer": qa.answer}
            for qa in (verify.review_qa_list or [] if verify else [])
        ]
        return await self._manager.jev.probability(
            {
                "group_id": group_id,
                "username": request.username,
                "verify_message": (verify.verify_message or "") if verify else "",
                "qa_pairs": qa_pairs,
                "risk_tips": request.risk_tips or "",
            },
            self._manager.catalog.jev_join("is_risky_instructions"),
        )

    async def approve(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        request_id: str | None = None,
        operator_id: str = "bot",
    ) -> ActionOutcome:
        try:
            await gateway.approval_join_request(
                group_id, member_id, op="approve", join_request_id=request_id
            )
        except Exception as exc:
            return self._failed("approve", group_id, member_id, operator_id, exc)
        self._manager.safeguard.increment_daily(group_id, "approve")
        self._audit(group_id, "approve", member_id, operator_id, "approved")
        return ActionOutcome(
            succeeded=True,
            action="approve",
            message=self._manager.catalog.format_fallback(
                "approve_done", request_id=request_id or "-", member_id=member_id
            ),
        )

    async def reject(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        request_id: str | None = None,
        reason: str = "rejected",
        blacklist: bool = False,
        operator_id: str = "bot",
    ) -> ActionOutcome:
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
            return self._failed("reject", group_id, member_id, operator_id, exc)
        self._manager.safeguard.increment_daily(group_id, "reject")
        self._audit(group_id, "reject", member_id, operator_id, reason)
        return ActionOutcome(
            succeeded=True,
            action="reject",
            message=self._manager.catalog.format_fallback(
                "reject_done",
                request_id=request_id or "-",
                member_id=member_id,
                reason=reason,
            ),
        )

    async def review(
        self, gateway: Gateway, group_id: str, request: JoinRequest
    ) -> ActionOutcome | None:
        """Decide and act on one join request event; None means ignored."""
        cfg = self.config(group_id)
        if not cfg.enabled:
            return None
        bot_role = await self._manager.identity.bot_role(gateway, group_id)
        if bot_role == "member":
            return None

        catalog = self._manager.catalog
        decision = cfg.default_action
        reason = catalog.format_fallback("auto_approve_reason")
        if cfg.reject_on_risk_tips and request.risk_tips:
            decision, reason = "reject", catalog.format_fallback("auto_reject_risk")
        elif cfg.use_jev_review and self._manager.jev.is_ready:
            try:
                risky = await self.risk_probability(group_id, request)
            except Exception:
                risky = 0.0
            if risky >= cfg.reject_threshold:
                decision, reason = "reject", catalog.format_fallback("auto_reject_jev")

        if decision == "ignore" or self._over_daily_limit(
            group_id, decision, cfg, owner=bot_role == "owner"
        ):
            return None
        if decision == "approve":
            return await self.approve(
                gateway,
                group_id,
                request.member_openid,
                request_id=request.join_request_id,
            )
        return await self.reject(
            gateway,
            group_id,
            request.member_openid,
            request_id=request.join_request_id,
            reason=reason,
        )

    def _over_daily_limit(
        self, group_id: str, decision: str, cfg: ApprovalConfig, *, owner: bool
    ) -> bool:
        if owner:
            return False
        limit = (
            cfg.daily_approve_limit if decision == "approve" else cfg.daily_reject_limit
        )
        return self._manager.safeguard.daily_count(group_id, decision) >= limit

    def _failed(
        self,
        action: str,
        group_id: str,
        member_id: str,
        operator_id: str,
        exc: Exception,
    ) -> ActionOutcome:
        self._audit(group_id, action, member_id, operator_id, str(exc), False)
        return ActionOutcome(
            succeeded=False,
            action=action,
            message=self._manager.catalog.format_fallback("action_failed", reason=exc),
        )

    def _audit(
        self,
        group_id: str,
        action: str,
        target_id: str,
        operator_id: str,
        reason: str,
        succeeded: bool = True,
    ) -> None:
        self._manager.audit.record(
            AuditRecord(
                group_id=group_id,
                action=action,
                target_id=target_id,
                operator_id=operator_id,
                reason=reason,
                succeeded=succeeded,
            )
        )


__all__ = ["ApprovalConfig", "ApprovalModule"]
