"""Direct Official QQ Bot v2 group actions and Jev-assisted join-request review."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time
from typing import Literal

from opsmesh.log import logger
from qq import Gateway, JoinRequest, SetMemberMuteState

from qq_admin.config import AutoApproveConfig, render_fallback_message
from qq_admin.jev import evaluate_join_request
from qq_admin.state import PluginRuntime

from .guard import (
    MuteDuration,
    check_action_guard,
    format_duration_short,
    is_group_enabled,
    match_escalation_step,
    parse_mute_duration,
    refresh_bot_role,
)


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Compact outcome returned by every direct moderation action."""

    ok: bool
    action: str
    summary: str
    blocked_step: str = ""
    escalated_to: str = ""


def _warn_policy(
    runtime: PluginRuntime, category: Literal["spam", "abuse", "ad"]
) -> tuple[int, int]:
    wc = runtime.config.warning
    if category == "spam":
        return wc.spam_threshold, wc.spam_window_seconds
    if category == "ad":
        return wc.ad_threshold, wc.ad_window_seconds
    return wc.abuse_threshold, wc.abuse_window_seconds


async def warn_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    category: Literal["spam", "abuse", "ad"],
    reason: str,
    operator_openid: str = "bot",
) -> ActionResult:
    """Record a windowed warning and audit entry after role-aware guard checks."""
    async with runtime.state.lock:
        decision = await check_action_guard(
            gateway,
            runtime.config,
            runtime.state,
            group_openid=group_openid,
            target_openid=member_openid,
            action="warn",
        )
        if not decision.allowed:
            return ActionResult(
                ok=False,
                action="warn",
                summary=render_fallback_message(
                    runtime.prompts, "action_blocked", reason=decision.reason
                ),
                blocked_step=decision.step,
            )

        threshold, window = _warn_policy(runtime, category)
        extra = ""
        if runtime.config.warning.enabled:
            count = runtime.state.add_warning(
                group_openid, member_openid, category, window
            )
            if count >= threshold:
                extra = render_fallback_message(
                    runtime.prompts,
                    "warn_threshold_hint",
                    current=count,
                    threshold=threshold,
                )

        runtime.state.record_op(
            group_openid=group_openid,
            action="warn",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=f"[{category}] {reason}",
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "warn")
        summary = render_fallback_message(
            runtime.prompts,
            "warn_done",
            member_openid=member_openid,
            violation_type=category,
            reason=reason,
            extra=extra,
        )
        return ActionResult(ok=True, action="warn", summary=summary)


async def mute_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    duration: MuteDuration,
    reason: str = "policy",
    operator_openid: str = "bot",
) -> ActionResult:
    """Mute one group member via Official QQ v2 set_group_members_mute."""
    try:
        seconds = parse_mute_duration(duration)
    except ValueError as exc:
        return ActionResult(
            ok=False,
            action="mute",
            summary=render_fallback_message(
                runtime.prompts, "action_failed", reason=str(exc)
            ),
        )

    async with runtime.state.lock:
        decision = await check_action_guard(
            gateway,
            runtime.config,
            runtime.state,
            group_openid=group_openid,
            target_openid=member_openid,
            action="mute",
            duration_seconds=seconds,
        )
        if not decision.allowed:
            return ActionResult(
                ok=False,
                action="mute",
                summary=render_fallback_message(
                    runtime.prompts, "action_blocked", reason=decision.reason
                ),
                blocked_step=decision.step,
            )

        effective_seconds = decision.adjusted_duration or seconds
        item = SetMemberMuteState(
            member_openid=member_openid,
            op="add",
            mute_expire_at=timedelta(seconds=effective_seconds),
        )
        try:
            await gateway.set_group_members_mute(group_openid, [item])
        except Exception as exc:
            runtime.state.record_op(
                group_openid=group_openid,
                action="mute",
                target_openid=member_openid,
                operator_openid=operator_openid,
                reason=reason,
                success=False,
            )
            return ActionResult(
                ok=False,
                action="mute",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )

        runtime.state.increment_daily(group_openid, "mute")
        runtime.state.last_mute_at[(group_openid, member_openid)] = time.time()
        runtime.state.record_op(
            group_openid=group_openid,
            action="mute",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=f"{format_duration_short(effective_seconds)}: {reason}",
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "mute")
        summary = render_fallback_message(
            runtime.prompts,
            "mute_done",
            member_openid=member_openid,
            duration=format_duration_short(effective_seconds),
            reason=reason,
        )
        return ActionResult(
            ok=True,
            action="mute",
            summary=summary,
            escalated_to=decision.escalated_action or "",
        )


async def unmute_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    operator_openid: str = "bot",
) -> ActionResult:
    """Unmute one group member via Official QQ v2 set_group_members_mute(op='del')."""
    async with runtime.state.lock:
        bot_role = await refresh_bot_role(
            gateway, runtime.config, runtime.state, group_openid
        )
        if bot_role not in ("owner", "admin"):
            return ActionResult(
                ok=False,
                action="unmute",
                summary=render_fallback_message(runtime.prompts, "bot_not_admin"),
                blocked_step="bot_role",
            )
        item = SetMemberMuteState(member_openid=member_openid, op="del")
        try:
            await gateway.set_group_members_mute(group_openid, [item])
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="unmute",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )

        runtime.state.record_op(
            group_openid=group_openid,
            action="unmute",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason="unmute",
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "unmute")
        return ActionResult(
            ok=True,
            action="unmute",
            summary=render_fallback_message(
                runtime.prompts, "unmute_done", member_openid=member_openid
            ),
        )


async def kick_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    reason: str = "policy",
    add_to_blacklist: bool = False,
    operator_openid: str = "bot",
    require_member_check: bool = False,
) -> ActionResult:
    """Remove a member via Official QQ v2 batch_remove_group_members."""
    async with runtime.state.lock:
        decision = await check_action_guard(
            gateway,
            runtime.config,
            runtime.state,
            group_openid=group_openid,
            target_openid=member_openid,
            action="kick",
            require_member_check=require_member_check,
        )
        if not decision.allowed:
            return ActionResult(
                ok=False,
                action="kick",
                summary=render_fallback_message(
                    runtime.prompts, "action_blocked", reason=decision.reason
                ),
                blocked_step=decision.step,
            )

        blacklist_flag = add_to_blacklist or decision.escalate_blacklist
        try:
            await gateway.batch_remove_group_members(
                group_openid,
                [member_openid],
                add_to_member_blacklist=blacklist_flag,
            )
        except Exception as exc:
            runtime.state.record_op(
                group_openid=group_openid,
                action="kick",
                target_openid=member_openid,
                operator_openid=operator_openid,
                reason=reason,
                success=False,
            )
            return ActionResult(
                ok=False,
                action="kick",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )

        runtime.state.increment_daily(group_openid, "kick")
        runtime.state.record_op(
            group_openid=group_openid,
            action="kick",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=reason,
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "kick")
        return ActionResult(
            ok=True,
            action="kick",
            summary=render_fallback_message(
                runtime.prompts,
                "kick_done",
                member_openid=member_openid,
                blacklist=str(blacklist_flag).lower(),
                reason=reason,
            ),
        )


async def ban_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    reason: str = "blacklist",
    operator_openid: str = "bot",
) -> ActionResult:
    """Add a member to the Official QQ v2 group blacklist."""
    async with runtime.state.lock:
        decision = await check_action_guard(
            gateway,
            runtime.config,
            runtime.state,
            group_openid=group_openid,
            target_openid=member_openid,
            action="ban",
        )
        if not decision.allowed:
            return ActionResult(
                ok=False,
                action="ban",
                summary=render_fallback_message(
                    runtime.prompts, "action_blocked", reason=decision.reason
                ),
                blocked_step=decision.step,
            )
        try:
            res = await gateway.post_group_member_blacklist(
                group_openid, op="add", member_openids=[member_openid]
            )
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="ban",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )
        if member_openid in res.fail_openids:
            return ActionResult(
                ok=False,
                action="ban",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason="platform rejected openid"
                ),
            )
        runtime.state.record_op(
            group_openid=group_openid,
            action="ban",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=reason,
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "ban")
        return ActionResult(
            ok=True,
            action="ban",
            summary=render_fallback_message(
                runtime.prompts, "ban_done", member_openid=member_openid
            ),
        )


async def unban_member(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    operator_openid: str = "bot",
) -> ActionResult:
    """Remove a member from the Official QQ v2 group blacklist."""
    async with runtime.state.lock:
        bot_role = await refresh_bot_role(
            gateway, runtime.config, runtime.state, group_openid
        )
        if bot_role not in ("owner", "admin"):
            return ActionResult(
                ok=False,
                action="unban",
                summary=render_fallback_message(runtime.prompts, "bot_not_admin"),
                blocked_step="bot_role",
            )
        try:
            res = await gateway.post_group_member_blacklist(
                group_openid, op="del", member_openids=[member_openid]
            )
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="unban",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )
        if member_openid in res.fail_openids:
            return ActionResult(
                ok=False,
                action="unban",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason="platform rejected openid"
                ),
            )
        runtime.state.record_op(
            group_openid=group_openid,
            action="unban",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason="unban",
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "unban")
        return ActionResult(
            ok=True,
            action="unban",
            summary=render_fallback_message(
                runtime.prompts, "unban_done", member_openid=member_openid
            ),
        )


async def recall_message(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    message_id: str,
    target_openid: str = "",
    reason: str = "policy",
    operator_openid: str = "bot",
) -> ActionResult:
    """Recall a group message via Official QQ v2 delete_group_message."""
    async with runtime.state.lock:
        bot_role = await refresh_bot_role(
            gateway, runtime.config, runtime.state, group_openid
        )
        if bot_role not in ("owner", "admin"):
            return ActionResult(
                ok=False,
                action="recall",
                summary=render_fallback_message(runtime.prompts, "bot_not_admin"),
                blocked_step="bot_role",
            )
        try:
            await gateway.delete_group_message(group_openid, message_id)
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="recall",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )
        runtime.state.record_op(
            group_openid=group_openid,
            action="recall",
            target_openid=target_openid or message_id,
            operator_openid=operator_openid,
            reason=reason,
            success=True,
        )
        runtime.state.mark_tool_exec(group_openid, "recall")
        return ActionResult(
            ok=True,
            action="recall",
            summary=render_fallback_message(
                runtime.prompts, "recall_done", message_id=message_id
            ),
        )


async def approve_join(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    join_request_id: str,
    reason: str = "approved",
    operator_openid: str = "bot",
) -> ActionResult:
    """Approve a pending join request via Official QQ v2 approval_join_request."""
    async with runtime.state.lock:
        try:
            await gateway.approval_join_request(
                group_openid,
                member_openid,
                op="approve",
                join_request_id=join_request_id,
            )
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="approve",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )
        runtime.state.increment_daily(group_openid, "approve")
        runtime.state.record_op(
            group_openid=group_openid,
            action="approve",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=reason,
            success=True,
        )
        return ActionResult(
            ok=True,
            action="approve",
            summary=render_fallback_message(
                runtime.prompts,
                "approve_done",
                request_id=join_request_id,
                member_openid=member_openid,
            ),
        )


async def reject_join(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    join_request_id: str,
    reason: str = "rejected",
    add_to_blacklist: bool = False,
    operator_openid: str = "bot",
) -> ActionResult:
    """Decline a pending join request via Official QQ v2 approval_join_request."""
    async with runtime.state.lock:
        try:
            await gateway.approval_join_request(
                group_openid,
                member_openid,
                op="decline",
                join_request_id=join_request_id,
                reject_reason=reason,
                add_to_member_blacklist=add_to_blacklist,
            )
        except Exception as exc:
            return ActionResult(
                ok=False,
                action="reject",
                summary=render_fallback_message(
                    runtime.prompts, "action_failed", reason=str(exc)
                ),
            )
        runtime.state.increment_daily(group_openid, "reject")
        runtime.state.record_op(
            group_openid=group_openid,
            action="reject",
            target_openid=member_openid,
            operator_openid=operator_openid,
            reason=reason,
            success=True,
        )
        return ActionResult(
            ok=True,
            action="reject",
            summary=render_fallback_message(
                runtime.prompts,
                "reject_done",
                request_id=join_request_id,
                member_openid=member_openid,
                reason=reason,
            ),
        )


async def enforce_escalation_violation(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    member_openid: str,
    message_id: str,
    category: Literal["spam", "abuse", "ad"],
    severity: Literal["warn", "auto_enforce", "severe"],
    reason: str,
) -> list[ActionResult]:
    """Direct Jev-to-action enforcement when LLM decision agent is disabled."""
    results: list[ActionResult] = []
    if message_id and severity in ("auto_enforce", "severe"):
        results.append(
            await recall_message(
                gateway,
                runtime,
                group_openid=group_openid,
                message_id=message_id,
                target_openid=member_openid,
                reason=reason,
            )
        )

    if severity == "severe":
        results.append(
            await kick_member(
                gateway,
                runtime,
                group_openid=group_openid,
                member_openid=member_openid,
                reason=reason,
                add_to_blacklist=True,
            )
        )
        return results

    esc = match_escalation_step(
        runtime.config, runtime.state, group_openid, member_openid
    )
    if severity == "warn" and esc is None:
        results.append(
            await warn_member(
                gateway,
                runtime,
                group_openid=group_openid,
                member_openid=member_openid,
                category=category,
                reason=reason,
            )
        )
        return results

    if esc is not None and esc.action == "kick":
        results.append(
            await kick_member(
                gateway,
                runtime,
                group_openid=group_openid,
                member_openid=member_openid,
                reason=reason,
                add_to_blacklist=esc.add_to_blacklist,
            )
        )
        return results

    mute_seconds = esc.mute_seconds if esc is not None else 600
    results.append(
        await mute_member(
            gateway,
            runtime,
            group_openid=group_openid,
            member_openid=member_openid,
            duration=mute_seconds,
            reason=reason,
        )
    )
    return results


def _resolve_group_approve_policy(
    aa: AutoApproveConfig, group_openid: str
) -> tuple[bool, Literal["ignore", "approve", "reject"], int, int]:
    for ov in aa.groups:
        if ov.group_openid == group_openid:
            return (
                True,
                ov.default_action,
                ov.daily_approve_limit or aa.daily_approve_limit,
                ov.daily_reject_limit or aa.daily_reject_limit,
            )
    return (
        aa.enabled,
        aa.default_action,
        aa.daily_approve_limit,
        aa.daily_reject_limit,
    )


def _extract_verify_text(req: JoinRequest) -> tuple[str, list[dict[str, str]]]:
    parts: list[str] = []
    qa_pairs: list[dict[str, str]] = []
    if req.verify_info is not None:
        if req.verify_info.verify_message:
            parts.append(req.verify_info.verify_message)
        for qa in req.verify_info.review_qa_list or []:
            qa_pairs.append({"question": qa.question, "answer": qa.answer})
            if qa.answer:
                parts.append(qa.answer)
    return "\n".join(parts), qa_pairs


def _is_request_expired(req: JoinRequest, max_age: int) -> bool:
    if req.apply_at is None:
        return False
    now = datetime.now(UTC)
    if isinstance(req.apply_at, datetime):
        ts = req.apply_at if req.apply_at.tzinfo else req.apply_at.replace(tzinfo=UTC)
    else:
        try:
            raw = str(req.apply_at).replace("Z", "+00:00")
            ts = datetime.fromisoformat(raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            return False
    return (now - ts).total_seconds() > max_age


async def evaluate_and_handle_join_request(
    gateway: Gateway,
    runtime: PluginRuntime,
    *,
    group_openid: str,
    req: JoinRequest,
) -> ActionResult | None:
    """Evaluate one JoinRequest using platform risk_tips + injected JevClient."""
    aa = runtime.config.auto_approve
    enabled, default_action, appr_lim, rej_lim = _resolve_group_approve_policy(
        aa, group_openid
    )
    if not enabled or not req.join_request_id or not req.member_openid:
        return None
    if _is_request_expired(req, aa.max_pending_seconds):
        return None

    bot_role = await refresh_bot_role(
        gateway, runtime.config, runtime.state, group_openid
    )
    if bot_role not in ("owner", "admin"):
        return None
    is_owner = bot_role == "owner"

    verify_text, qa_pairs = _extract_verify_text(req)
    decision: Literal["ignore", "approve", "reject"] = default_action
    reason = render_fallback_message(runtime.prompts, "auto_approve_reason")

    if aa.reject_on_risk_tips and req.risk_tips:
        decision = "reject"
        reason = render_fallback_message(runtime.prompts, "auto_reject_risk")
    elif aa.use_jev_review and runtime.jev_client.is_ready:
        risk = await evaluate_join_request(
            runtime.jev_client,
            runtime.prompts,
            verify_message=verify_text,
            qa_pairs=qa_pairs,
            risk_tips=req.risk_tips,
        )
        if (
            risk.status == "ok"
            and risk.risk_probability >= runtime.config.jev.join_reject_threshold
        ):
            decision = "reject"
            reason = render_fallback_message(runtime.prompts, "auto_reject_jev")

    if decision == "approve":
        if (
            not is_owner
            and runtime.state.get_daily_count(group_openid, "approve") >= appr_lim
        ):
            return None
        return await approve_join(
            gateway,
            runtime,
            group_openid=group_openid,
            member_openid=req.member_openid,
            join_request_id=req.join_request_id,
            reason=reason,
        )

    if decision == "reject":
        if (
            not is_owner
            and runtime.state.get_daily_count(group_openid, "reject") >= rej_lim
        ):
            return None
        return await reject_join(
            gateway,
            runtime,
            group_openid=group_openid,
            member_openid=req.member_openid,
            join_request_id=req.join_request_id,
            reason=reason,
        )
    return None


async def scan_join_requests_once(
    gateway: Gateway, runtime: PluginRuntime
) -> list[ActionResult]:
    """Poll pending join requests across all configured groups once."""
    aa = runtime.config.auto_approve
    targets: set[str] = set()
    if aa.enabled:
        targets.update(runtime.config.auto_moderate.enabled_groups)
    for ov in aa.groups:
        if ov.group_openid:
            targets.add(ov.group_openid)

    override_ids = {g.group_openid for g in aa.groups}
    outcomes: list[ActionResult] = []
    for gid in sorted(targets):
        if gid not in override_ids and not is_group_enabled(
            runtime.config, runtime.state, gid
        ):
            continue
        try:
            page = await gateway.get_group_join_request_list(gid)
        except Exception as exc:
            logger.warning(f"qq_admin join request poll failed for {gid}: {exc}")
            continue
        for req in page.list:
            res = await evaluate_and_handle_join_request(
                gateway, runtime, group_openid=gid, req=req
            )
            if res is not None:
                outcomes.append(res)
    return outcomes


__all__ = [
    "ActionResult",
    "approve_join",
    "ban_member",
    "enforce_escalation_violation",
    "evaluate_and_handle_join_request",
    "kick_member",
    "mute_member",
    "recall_message",
    "reject_join",
    "scan_join_requests_once",
    "unban_member",
    "unmute_member",
    "warn_member",
]
