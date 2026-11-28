"""Tests for deterministic module singletons, multi-bot/group isolation, and auth."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    GroupBotStateReturn,
    GroupMemberInfo,
    JoinRequest,
    MemberBlacklistOpReturn,
    VerifyInfo,
)

from qq_admin import (
    APPROVAL,
    AUDIT,
    IDENTITY,
    MANAGER,
    MODERATION,
    SAFEGUARD,
    WARNING,
    Config,
    SafetyReport,
    format_duration,
    parse_duration,
)


def _fake_gateway(
    *,
    self_id: str = "BOT_1",
    bot_role: str = "admin",
    roles: dict[str, str] | None = None,
):
    role_map = roles or {}
    gw = MagicMock()
    gw.self_id = self_id
    gw.get_group_bot_state = AsyncMock(
        return_value=GroupBotStateReturn(member_role=bot_role)
    )
    gw.get_group_member = AsyncMock(
        side_effect=lambda gid, uid: GroupMemberInfo(
            member_openid=uid, member_role=role_map.get(uid, "member")
        )
    )
    gw.set_group_members_mute = AsyncMock()
    gw.batch_remove_group_members = AsyncMock()
    gw.post_group_member_blacklist = AsyncMock(return_value=MemberBlacklistOpReturn())
    gw.delete_group_message = AsyncMock()
    gw.approval_join_request = AsyncMock()
    return gw


def test_parse_and_format_duration() -> None:
    assert parse_duration("10m").seconds == 600  # type: ignore[union-attr]
    assert parse_duration("2h").seconds == 7200  # type: ignore[union-attr]
    assert parse_duration("1d").seconds == 86400  # type: ignore[union-attr]
    assert parse_duration(3_000_000).seconds == 2_592_000  # type: ignore[union-attr]
    assert parse_duration("bad") is None
    assert format_duration(600) == "10m"
    assert format_duration(3600) == "1h"


@pytest.mark.anyio
async def test_multi_bot_role_cache_and_safeguard_8_steps() -> None:
    IDENTITY.update_config(None, "admins", "GLOBAL_ADMIN")
    SAFEGUARD.update_config("G1", "protected_users", "VIP_1")
    SAFEGUARD.add_exempt("G1", "EXEMPT_1")

    gw_admin = _fake_gateway(
        self_id="BOT_ADMIN",
        bot_role="admin",
        roles={"MOD_1": "admin", "USER_1": "member"},
    )
    gw_owner = _fake_gateway(self_id="BOT_OWNER", bot_role="owner")

    assert await IDENTITY.bot_role(gw_admin, "G1") == "admin"
    assert await IDENTITY.bot_role(gw_owner, "G1") == "owner"

    assert SAFEGUARD.is_whitelisted("G1", "VIP_1")
    assert SAFEGUARD.is_whitelisted("G1", "EXEMPT_1")
    assert SAFEGUARD.is_whitelisted("G1", "GLOBAL_ADMIN")
    assert not SAFEGUARD.is_whitelisted("G1", "USER_1")

    v1 = await SAFEGUARD.check_action(gw_admin, "G1", "VIP_1", "mute", mute_seconds=600)
    assert not v1.allowed
    assert v1.blocked_by == "protected_users"

    v2 = await SAFEGUARD.check_action(
        gw_admin, "G1", "EXEMPT_1", "mute", mute_seconds=600
    )
    assert not v2.allowed
    assert v2.blocked_by == "exempt_users"

    v3 = await SAFEGUARD.check_action(
        gw_admin, "G1", "GLOBAL_ADMIN", "mute", mute_seconds=600
    )
    assert not v3.allowed
    assert v3.blocked_by == "auto_exempt_admins"

    v4 = await SAFEGUARD.check_action(gw_admin, "G1", "MOD_1", "mute", mute_seconds=600)
    assert not v4.allowed
    assert v4.blocked_by == "auto_exempt_admins"

    v5 = await SAFEGUARD.check_action(
        gw_admin, "G1", "USER_1", "kick", require_confirm=True
    )
    assert not v5.allowed
    assert v5.blocked_by == "kick_require_confirm"

    SAFEGUARD.mark_member_verified("G1", "USER_1")
    v5_ok = await SAFEGUARD.check_action(
        gw_admin, "G1", "USER_1", "kick", require_confirm=True
    )
    assert v5_ok.allowed

    v_owner = await SAFEGUARD.check_action(
        gw_owner, "G1", "VIP_1", "mute", mute_seconds=7200
    )
    assert v_owner.allowed
    assert v_owner.effective_mute_seconds == 7200


@pytest.mark.anyio
async def test_operator_auth_auto_escalations_flood_and_approval_short_circuits() -> (
    None
):
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock(
        return_value=SimpleNamespace(nouls={"answer": SimpleNamespace(noul=0.92)})
    )
    MANAGER.setup(Config(), jev_client=fake_jev)
    gw = _fake_gateway(
        bot_role="admin",
        roles={"ADMIN_1": "admin", "U1": "member", "U2": "member"},
    )

    # Non-admin operator_id calling exported module API directly is blocked
    denied = await MODERATION.mute(gw, "G1", "U2", duration=600, operator_id="U1")
    assert not denied.succeeded
    assert denied.blocked_by == "permission_denied"
    gw.set_group_members_mute.assert_not_awaited()

    denied_approve = await APPROVAL.approve(gw, "G1", "NEW_1", operator_id="U1")
    assert not denied_approve.succeeded
    assert denied_approve.blocked_by == "permission_denied"

    # Admin operator_id succeeds
    ok_unmute = await MODERATION.unmute(gw, "G1", "U2", operator_id="ADMIN_1")
    assert ok_unmute.succeeded

    # Warning reaching ad_threshold=1 automatically upgrades to mute!
    SAFEGUARD.update_config("G1", "mute_cooldown", "0")
    w = await MODERATION.warn(gw, "G1", "U1", category="ad", reason="promo")
    assert w.succeeded
    assert w.action == "mute"

    # Escalation ladder: 3 prior actions within 72h auto-upgrades mute -> kick!
    WARNING.update_config("G1", "spam_threshold", "10")
    await MODERATION.warn(gw, "G1", "U2", category="spam", reason="s1")
    await MODERATION.warn(gw, "G1", "U2", category="spam", reason="s2")
    await MODERATION.warn(gw, "G1", "U2", category="spam", reason="s3")
    escalated = await MODERATION.mute(gw, "G1", "U2", duration=600, reason="s4")
    assert escalated.succeeded
    assert escalated.action == "kick"
    gw.batch_remove_group_members.assert_awaited_once_with(
        "G1", ["U2"], add_to_member_blacklist=True
    )

    # Flood/repeat limiter triggers in pure code without calling Jev
    fake_jev.system_one.reset_mock()
    MODERATION.update_config("G1", "repeat_max_messages", "3")
    assert MODERATION.check_flood("G1", "FLOOD_U", "copy paste") is None
    assert MODERATION.check_flood("G1", "FLOOD_U", "copy paste") is None
    assert MODERATION.check_flood("G1", "FLOOD_U", "copy paste") == "repeat"

    # Trusted-domain-only message skips Jev completely
    safe_link = await MODERATION.assess(
        "G1",
        text="https://github.com/jhupo/OpsMesh",
        urls=["https://github.com/jhupo/OpsMesh"],
    )
    assert safe_link.max_risk == 0.0
    fake_jev.system_one.assert_not_awaited()

    # Join approval: empty request & exhausted quota short-circuit Jev
    APPROVAL.update_config("G1", "enabled", "true")
    APPROVAL.update_config("G1", "default_action", "approve")

    empty_req = JoinRequest(join_request_id="REQ_EMPTY", member_openid="CLEAN_1")
    res_empty = await APPROVAL.review(gw, "G1", empty_req)
    assert res_empty is not None
    assert res_empty.action == "approve"
    fake_jev.system_one.assert_not_awaited()

    jev_req = JoinRequest(
        join_request_id="REQ_JEV",
        member_openid="BAD_2",
        verify_info=VerifyInfo(verify_message="add wechat for cheap promo"),
    )
    res_jev = await APPROVAL.review(gw, "G1", jev_req)
    assert res_jev is not None
    assert res_jev.action == "reject"
    fake_jev.system_one.assert_awaited_once()

    # Exhaust reject quota under default_action="ignore" -> Jev is short-circuited!
    fake_jev.system_one.reset_mock()
    APPROVAL.update_config("G1", "default_action", "ignore")
    APPROVAL.update_config("G1", "daily_reject_limit", "1")
    res_quota = await APPROVAL.review(gw, "G1", jev_req)
    assert res_quota is None
    fake_jev.system_one.assert_not_awaited()

    route, hits = MODERATION.classify_route(
        "G1", SafetyReport(violence=0.92, severity=4)
    )
    assert route == "critical"
    assert hits == ["violence"]

    route_atk, _ = MODERATION.classify_route(
        "G1", SafetyReport(prompt_injection=0.88, severity=2)
    )
    assert route_atk == "attack"

    assert len(AUDIT.recent_logs("G1", limit=50)) >= 5
