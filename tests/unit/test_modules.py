"""Tests for feature modules (identity, safeguard, moderation, approval)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    GroupBotStateReturn,
    GroupMemberInfo,
    JoinRequest,
    MemberBlacklistOpReturn,
)

from qq_admin import ServiceManager, format_duration, parse_duration


def _fake_gateway(*, bot_role: str = "admin", roles: dict[str, str] | None = None):
    role_map = roles or {}
    gw = MagicMock()
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
async def test_safeguard_8_steps_and_owner_bypass() -> None:
    manager = ServiceManager()
    manager.identity.update_config("G1", "admins", "GLOBAL_ADMIN")
    manager.safeguard.update_config("G1", "protected_users", "VIP_1")
    manager.safeguard.add_exempt("G1", "EXEMPT_1")

    gw = _fake_gateway(bot_role="admin", roles={"MOD_1": "admin", "USER_1": "member"})

    # 1. protected_users
    v1 = await manager.safeguard.check_action(
        gw, "G1", "VIP_1", "mute", mute_seconds=600
    )
    assert not v1.allowed
    assert v1.blocked_by == "protected_users"
    # 2. exempt_users
    v2 = await manager.safeguard.check_action(
        gw, "G1", "EXEMPT_1", "mute", mute_seconds=600
    )
    assert not v2.allowed
    assert v2.blocked_by == "exempt_users"
    # 3. global admins & group admins (unified auto_exempt_admins via is_admin)
    v3 = await manager.safeguard.check_action(
        gw, "G1", "GLOBAL_ADMIN", "mute", mute_seconds=600
    )
    assert not v3.allowed
    assert v3.blocked_by == "auto_exempt_admins"
    # 4. group admin
    v4 = await manager.safeguard.check_action(
        gw, "G1", "MOD_1", "mute", mute_seconds=600
    )
    assert not v4.allowed
    assert v4.blocked_by == "auto_exempt_admins"
    # 5. kick_require_confirm
    v5 = await manager.safeguard.check_action(
        gw, "G1", "USER_1", "kick", require_confirm=True
    )
    assert not v5.allowed
    assert v5.blocked_by == "kick_require_confirm"
    manager.safeguard.mark_member_verified("G1", "USER_1")
    v5_ok = await manager.safeguard.check_action(
        gw, "G1", "USER_1", "kick", require_confirm=True
    )
    assert v5_ok.allowed

    # Owner bot bypasses safeguard limits
    manager.identity.forget_group("G1")
    owner_gw = _fake_gateway(bot_role="owner")
    v_owner = await manager.safeguard.check_action(
        owner_gw, "G1", "VIP_1", "mute", mute_seconds=7200
    )
    assert v_owner.allowed
    assert v_owner.effective_mute_seconds == 7200


@pytest.mark.anyio
async def test_moderation_actions_and_join_approval() -> None:
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock(
        return_value=SimpleNamespace(nouls={"answer": SimpleNamespace(noul=0.92)})
    )
    manager = ServiceManager(jev_client=fake_jev)
    gw = _fake_gateway(bot_role="admin")

    w = await manager.moderation.warn(gw, "G1", "U1", category="ad", reason="promo")
    assert w.succeeded
    m = await manager.moderation.mute(gw, "G1", "U1", duration="10m", reason="spam")
    assert m.succeeded
    gw.set_group_members_mute.assert_awaited_once()

    u = await manager.moderation.unmute(gw, "G1", "U1")
    assert u.succeeded
    b = await manager.moderation.ban(gw, "G1", "U2", reason="scam")
    assert b.succeeded
    ub = await manager.moderation.unban(gw, "G1", "U2")
    assert ub.succeeded
    r = await manager.moderation.recall(gw, "G1", "MSG_1", reason="ad")
    assert r.succeeded
    assert len(manager.audit.recent_logs("G1", limit=20)) >= 6

    # ApprovalModule: risk_tips and Jev auto-reject
    manager.approval.update_config("G1", "enabled", "true")
    manager.approval.update_config("G1", "default_action", "approve")
    risky_req = JoinRequest(
        join_request_id="REQ_1", member_openid="BAD_1", risk_tips="spam account"
    )
    res1 = await manager.approval.review(gw, "G1", risky_req)
    assert res1 is not None
    assert res1.action == "reject"

    jev_risky_req = JoinRequest(join_request_id="REQ_2", member_openid="BAD_2")
    res2 = await manager.approval.review(gw, "G1", jev_risky_req)
    assert res2 is not None
    assert res2.action == "reject"
