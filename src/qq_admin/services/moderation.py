"""Unified moderation orchestrator wrapping all 12 `qq.Gateway` v2 group admin APIs."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from qq import SetMemberMuteState

from qq_admin.config import QQAdminConfig
from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.exception import QQAdminError
from qq_admin.store import StateStoreProtocol
from qq_admin.typing import (
    AuditSource,
    AuditStatus,
    EscalationAction,
    RoleTier,
    ViolationType,
    parse_role_tier,
)

from .audit import AuditService
from .identity import IdentityService
from .safeguard import SafeguardPass, SafeguardService
from .warning import WarningService


class ModerationService:
    """Single source of truth for all QQ v2 group-admin commands and public APIs."""

    def __init__(
        self,
        *,
        config: QQAdminConfig,
        store: StateStoreProtocol,
        identity: IdentityService,
        safeguard: SafeguardService,
        warning: WarningService,
        audit: AuditService,
    ) -> None:
        self._config = config
        self._store = store
        self._identity = identity
        self._safeguard = safeguard
        self._warning = warning
        self._audit = audit

    @asynccontextmanager
    async def _guarded(
        self,
        ctx: AdminContext,
        *,
        action: str,
        target_openid: str = "",
        extra_targets: Sequence[str] = (),
        require_bot_admin: bool = True,
        check_target_role: bool = False,
        quota_key: str | None = None,
        daily_limit: int | None = None,
    ) -> AsyncIterator[SafeguardPass]:
        """Run shared pre-flight safeguards and auto-record DENIED audits on failure."""
        try:
            await self._safeguard.ensure_group_enabled(ctx.group_openid)
            self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
            if require_bot_admin:
                await self._identity.ensure_bot_admin(ctx.gateway, ctx.group_openid)

            self_info = getattr(ctx.gateway, "self_info", None)
            bot_uid = self_info.id if self_info else None
            if target_openid and check_target_role:
                info = await ctx.gateway.get_group_member(
                    ctx.group_openid, target_openid
                )
                self._safeguard.ensure_target_mutable(
                    ctx,
                    target_openid=target_openid,
                    target_role=info.member_role,
                    bot_openid=bot_uid,
                )
            for mid in extra_targets:
                self._safeguard.ensure_target_mutable(
                    ctx, target_openid=mid, bot_openid=bot_uid
                )

            guard = (
                await self._safeguard.check_cooldown_and_quota(
                    ctx,
                    action_key=quota_key,
                    target_openid=target_openid,
                    daily_limit=daily_limit,
                )
                if quota_key is not None
                else SafeguardPass()
            )
        except QQAdminError as exc:
            await self._audit.record(
                ctx,
                action=action,
                status=AuditStatus.DENIED,
                target_openid=target_openid,
                detail=exc.message,
            )
            raise
        yield guard

    # --- Group Switch & Status ---

    async def set_group_enabled(
        self, ctx: AdminContext, *, enabled: bool
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.OWNER)
        await self._store.set_group_enabled(ctx.group_openid, enabled)
        state_str = "enabled" if enabled else "disabled"
        await self._audit.record(
            ctx,
            action="set_group_enabled",
            status=AuditStatus.SUCCESS,
            detail=state_str,
        )
        return ModerationOutcome(
            action="set_group_enabled",
            group_openid=ctx.group_openid,
            summary=f"Group administration {state_str}.",
            data={"enabled": enabled},
        )

    async def get_group_info(self, ctx: AdminContext) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        info = await ctx.gateway.get_group_info(ctx.group_openid)
        return ModerationOutcome(
            action="get_group_info",
            group_openid=ctx.group_openid,
            summary=f"Group: {info.group_name}, members: {info.member_count}",
            data=info.model_dump(),
        )

    async def get_bot_state(
        self, ctx: AdminContext, *, force_refresh: bool = False
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        state = await ctx.gateway.get_group_bot_state(ctx.group_openid)
        role = parse_role_tier(state.member_role)
        await self._store.set_cached_bot_role(
            ctx.group_openid,
            role,
            ttl_seconds=self._config.safeguard.bot_role_cache_ttl_seconds,
        )
        return ModerationOutcome(
            action="get_bot_state",
            group_openid=ctx.group_openid,
            summary=(
                f"Bot role: {role.value}, "
                f"allow_proactive_msg: {state.allow_proactive_msg}"
            ),
            data=state.model_dump(),
        )

    async def get_audit_log(
        self,
        ctx: AdminContext,
        *,
        limit: int = 20,
        source: AuditSource | None = None,
        action: str | None = None,
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        records = await self._audit.query(
            ctx.group_openid, limit=limit, source=source, action=action
        )
        return ModerationOutcome(
            action="get_audit_log",
            group_openid=ctx.group_openid,
            summary=f"Found {len(records)} audit record(s).",
            data={"records": [r.model_dump(mode="json") for r in records]},
        )

    # --- Member Queries ---

    async def get_member(
        self, ctx: AdminContext, *, member_openid: str
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        member = await ctx.gateway.get_group_member(ctx.group_openid, member_openid)
        return ModerationOutcome(
            action="get_member",
            group_openid=ctx.group_openid,
            summary=(
                f"Member {member.username or member.member_openid} "
                f"role: {member.member_role}"
            ),
            data=member.model_dump(),
        )

    async def list_members(
        self,
        ctx: AdminContext,
        *,
        cursor: str | None = None,
        limit: int | None = 50,
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        res = await ctx.gateway.get_group_members(
            ctx.group_openid, cursor=cursor, limit=limit
        )
        return ModerationOutcome(
            action="list_members",
            group_openid=ctx.group_openid,
            summary=f"Returned {len(res.members)} member(s) (is_end={res.is_end}).",
            data=res.model_dump(),
        )

    # --- Warning & Escalation ---

    async def warn_member(
        self,
        ctx: AdminContext,
        *,
        member_openid: str,
        violation_type: ViolationType = ViolationType.OTHER,
        reason: str = "",
    ) -> ModerationOutcome:
        async with self._guarded(
            ctx,
            action="warn_member",
            target_openid=member_openid,
            require_bot_admin=False,
            check_target_role=True,
        ):
            esc = await self._warning.record_violation(
                group_openid=ctx.group_openid,
                member_openid=member_openid,
                violation_type=violation_type,
                reason=reason,
                operator_openid=ctx.operator.openid,
            )

        escalated_summary = await self._apply_escalation(
            ctx, member_openid=member_openid, esc=esc, reason=reason
        )
        summary = (
            f"Recorded violation ({violation_type.value}) for {member_openid}; "
            f"active count={esc.active_count}{escalated_summary}"
        )
        await self._audit.record(
            ctx,
            action="warn_member",
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=summary,
        )
        return ModerationOutcome(
            action="warn_member",
            group_openid=ctx.group_openid,
            summary=summary,
            data={
                "member_openid": member_openid,
                "active_count": esc.active_count,
                "escalation": esc.action.value,
            },
        )

    async def _apply_escalation(
        self, ctx: AdminContext, *, member_openid: str, esc, reason: str
    ) -> str:
        if esc.action == EscalationAction.AUTO_MUTE:
            res = await self.mute_member(
                ctx,
                member_openid=member_openid,
                duration_seconds=esc.mute_duration_seconds,
                reason=f"Auto-muted after {esc.active_count} violation(s): {reason}",
            )
            return f" -> auto-muted ({res.summary})"
        if esc.action == EscalationAction.AUTO_KICK:
            res = await self.kick_member(
                ctx,
                member_openid=member_openid,
                add_to_blacklist=esc.kick_with_blacklist,
                reason=f"Auto-kicked after {esc.active_count} violation(s): {reason}",
            )
            return f" -> auto-kicked ({res.summary})"
        return ""

    async def clear_warnings(
        self, ctx: AdminContext, *, member_openid: str
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        cleared = await self._warning.clear_warnings(ctx.group_openid, member_openid)
        summary = f"Cleared {cleared} warning(s) for {member_openid}."
        await self._audit.record(
            ctx,
            action="clear_warnings",
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=summary,
        )
        return ModerationOutcome(
            action="clear_warnings",
            group_openid=ctx.group_openid,
            summary=summary,
            data={"member_openid": member_openid, "cleared": cleared},
        )

    # --- Mute & Unmute ---

    async def get_mute_setting(self, ctx: AdminContext) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        setting = await ctx.gateway.get_group_mute_setting(ctx.group_openid)
        return ModerationOutcome(
            action="get_mute_setting",
            group_openid=ctx.group_openid,
            summary=f"Muted member count: {len(setting.muted_members)}",
            data=setting.model_dump(),
        )

    async def mute_member(
        self,
        ctx: AdminContext,
        *,
        member_openid: str,
        duration_seconds: int = 600,
        reason: str = "",
    ) -> ModerationOutcome:
        async with self._guarded(
            ctx,
            action="mute_member",
            target_openid=member_openid,
            check_target_role=True,
            quota_key="mute",
            daily_limit=self._config.safeguard.daily_mute_quota,
        ) as guard:
            clamped = self._safeguard.clamp_mute_duration(duration_seconds)
            await ctx.gateway.set_group_members_mute(
                ctx.group_openid,
                [
                    SetMemberMuteState(
                        member_openid=member_openid,
                        op="add",
                        mute_end_timestamp=timedelta(seconds=clamped),
                    )
                ],
            )
        summary = f"Muted {member_openid} for {clamped}s."
        data = {
            "member_openid": member_openid,
            "duration_seconds": clamped,
            "remaining_quota": guard.remaining_quota,
        }
        await self._audit.record(
            ctx,
            action="mute_member",
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=reason or summary,
            extra=data,
        )
        return ModerationOutcome(
            action="mute_member",
            group_openid=ctx.group_openid,
            summary=summary,
            data=data,
        )

    async def unmute_member(
        self, ctx: AdminContext, *, member_openid: str
    ) -> ModerationOutcome:
        async with self._guarded(
            ctx, action="unmute_member", target_openid=member_openid
        ):
            await ctx.gateway.set_group_members_mute(
                ctx.group_openid,
                [SetMemberMuteState(member_openid=member_openid, op="del")],
            )
        summary = f"Unmuted {member_openid}."
        await self._audit.record(
            ctx,
            action="unmute_member",
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=summary,
        )
        return ModerationOutcome(
            action="unmute_member",
            group_openid=ctx.group_openid,
            summary=summary,
            data={"member_openid": member_openid},
        )

    # --- Kick & Recall ---

    async def kick_member(
        self,
        ctx: AdminContext,
        *,
        member_openid: str,
        add_to_blacklist: bool = False,
        reason: str = "",
    ) -> ModerationOutcome:
        async with self._guarded(
            ctx,
            action="kick_member",
            target_openid=member_openid,
            check_target_role=True,
            quota_key="kick",
            daily_limit=self._config.safeguard.daily_kick_quota,
        ) as guard:
            res = await ctx.gateway.batch_remove_group_members(
                ctx.group_openid,
                [member_openid],
                add_to_member_blacklist=add_to_blacklist,
            )
        summary = (
            f"Removed member {member_openid}"
            f"{' and blacklisted' if add_to_blacklist else ''}."
        )
        await self._audit.record(
            ctx,
            action="kick_member",
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=reason or summary,
            extra={
                "add_to_blacklist": add_to_blacklist,
                "remaining_quota": guard.remaining_quota,
            },
        )
        return ModerationOutcome(
            action="kick_member",
            group_openid=ctx.group_openid,
            summary=summary,
            data={**res.model_dump(), "remaining_quota": guard.remaining_quota},
        )

    async def recall_message(
        self, ctx: AdminContext, *, message_id: str
    ) -> ModerationOutcome:
        async with self._guarded(ctx, action="recall_message"):
            await ctx.gateway.delete_group_message(ctx.group_openid, message_id)
        summary = f"Recalled message {message_id}."
        await self._audit.record(
            ctx,
            action="recall_message",
            status=AuditStatus.SUCCESS,
            detail=summary,
            extra={"message_id": message_id},
        )
        return ModerationOutcome(
            action="recall_message",
            group_openid=ctx.group_openid,
            summary=summary,
            data={"message_id": message_id},
        )

    # --- Blacklist ---

    async def list_blacklist(
        self,
        ctx: AdminContext,
        *,
        cursor: str | None = None,
        limit: int | None = 50,
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        await self._identity.ensure_bot_admin(ctx.gateway, ctx.group_openid)
        res = await ctx.gateway.get_group_member_blacklist(
            ctx.group_openid, cursor=cursor, limit=limit
        )
        return ModerationOutcome(
            action="list_blacklist",
            group_openid=ctx.group_openid,
            summary=f"Group blacklist count: {len(res.members)}.",
            data=res.model_dump(),
        )

    async def manage_blacklist(
        self,
        ctx: AdminContext,
        *,
        op: Literal["add", "del"],
        member_openids: list[str],
    ) -> ModerationOutcome:
        action_name = "add_blacklist" if op == "add" else "remove_blacklist"
        async with self._guarded(
            ctx,
            action=action_name,
            extra_targets=member_openids if op == "add" else (),
            quota_key="blacklist" if op == "add" else None,
            daily_limit=self._config.safeguard.daily_blacklist_quota
            if op == "add"
            else None,
        ):
            res = await ctx.gateway.post_group_member_blacklist(
                ctx.group_openid, op=op, member_openids=member_openids
            )
        verb = "added to" if op == "add" else "removed from"
        summary = f"{len(res.success_member_openids)} member(s) {verb} group blacklist."
        await self._audit.record(
            ctx,
            action=action_name,
            status=AuditStatus.SUCCESS,
            detail=summary,
            extra={"member_openids": member_openids},
        )
        return ModerationOutcome(
            action=action_name,
            group_openid=ctx.group_openid,
            summary=summary,
            data=res.model_dump(),
        )

    # --- Join Requests ---

    async def list_join_requests(
        self,
        ctx: AdminContext,
        *,
        cursor: str | None = None,
        limit: int | None = 50,
    ) -> ModerationOutcome:
        self._identity.ensure_operator_tier(ctx.operator, min_tier=RoleTier.ADMIN)
        await self._identity.ensure_bot_admin(ctx.gateway, ctx.group_openid)
        res = await ctx.gateway.get_group_join_request_list(
            ctx.group_openid, cursor=cursor, limit=limit
        )
        return ModerationOutcome(
            action="list_join_requests",
            group_openid=ctx.group_openid,
            summary=f"Pending join requests: {len(res.join_requests)}.",
            data=res.model_dump(),
        )

    async def decide_join_request(
        self,
        ctx: AdminContext,
        *,
        member_openid: str,
        op: Literal["approve", "decline"],
        join_request_id: str | None = None,
        reject_reason: str | None = None,
        add_to_blacklist: bool = False,
    ) -> ModerationOutcome:
        action_name = (
            "approve_join_request" if op == "approve" else "decline_join_request"
        )
        async with self._guarded(
            ctx,
            action=action_name,
            target_openid=member_openid,
            quota_key="approval",
            daily_limit=self._config.safeguard.daily_approval_quota,
        ):
            await ctx.gateway.approval_join_request(
                ctx.group_openid,
                member_openid,
                op=op,
                join_request_id=join_request_id,
                reject_reason=reject_reason,
                add_to_member_blacklist=add_to_blacklist if op == "decline" else None,
            )
        verb = "Approved" if op == "approve" else "Declined"
        summary = f"{verb} join request from {member_openid}."
        await self._audit.record(
            ctx,
            action=action_name,
            status=AuditStatus.SUCCESS,
            target_openid=member_openid,
            detail=reject_reason or summary,
            extra={"join_request_id": join_request_id},
        )
        return ModerationOutcome(
            action=action_name,
            group_openid=ctx.group_openid,
            summary=summary,
            data={
                "member_openid": member_openid,
                "op": op,
                "join_request_id": join_request_id,
            },
        )


__all__ = ["ModerationService"]
