"""Tests for direct module singletons (IDENTITY, SAFEGUARD, MODERATION, APPROVAL)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    GroupBotStateReturn,
    GroupMemberInfo,
    JoinRequest,
    MemberBlacklistOpReturn,
)

from qq_admin import (
    APPROVAL,
    AUDIT,
    IDENTITY,
    MANAGER,
    MODERATION,
    SAFEGUARD,
    Config,
    SafetyReport,
    format_duration,
    parse_duration,
)


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
    IDENTITY.update_config("G1", "admins", "GLOBAL_ADMIN")
    SAFEGUARD.update_config("G1", "protected_users", "VIP_1")
    SAFEGUARD.add_exempt("G1", "EXEMPT_1")

    gw = _fake_gateway(bot_role="admin", roles={"MOD_1": "admin", "USER_1": "member"})

    v1 = await SAFEGUARD.check_action(gw, "G1", "VIP_1", "mute", mute_seconds=600)
    assert not v1.allowed
    assert v1.blocked_by == "protected_users"

    v2 = await SAFEGUARD.check_action(gw, "G1", "EXEMPT_1", "mute", mute_seconds=600)
    assert not v2.allowed
    assert v2.blocked_by == "exempt_users"

    v3 = await SAFEGUARD.check_action(
        gw, "G1", "GLOBAL_ADMIN", "mute", mute_seconds=600
    )
    assert not v3.allowed
    assert v3.blocked_by == "auto_exempt_admins"

    v4 = await SAFEGUARD.check_action(gw, "G1", "MOD_1", "mute", mute_seconds=600)
    assert not v4.allowed
    assert v4.blocked_by == "auto_exempt_admins"

    v5 = await SAFEGUARD.check_action(gw, "G1", "USER_1", "kick", require_confirm=True)
    assert not v5.allowed
    assert v5.blocked_by == "kick_require_confirm"

    SAFEGUARD.mark_member_verified("G1", "USER_1")
    v5_ok = await SAFEGUARD.check_action(
        gw, "G1", "USER_1", "kick", require_confirm=True
    )
    assert v5_ok.allowed

    IDENTITY.forget_group("G1")
    owner_gw = _fake_gateway(bot_role="owner")
    v_owner = await SAFEGUARD.check_action(
        owner_gw, "G1", "VIP_1", "mute", mute_seconds=7200
    )
    assert v_owner.allowed
    assert v_owner.effective_mute_seconds == 7200


@pytest.mark.anyio
async def test_moderation_actions_routing_and_join_approval() -> None:
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock(
        return_value=SimpleNamespace(nouls={"answer": SimpleNamespace(noul=0.92)})
    )
    MANAGER.setup(Config(), jev_client=fake_jev)
    gw = _fake_gateway(bot_role="admin")

    w = await MODERATION.warn(gw, "G1", "U1", category="ad", reason="promo")
    assert w.succeeded
    m = await MODERATION.mute(gw, "G1", "U1", duration="10m", reason="spam")
    assert m.succeeded
    gw.set_group_members_mute.assert_awaited_once()

    u = await MODERATION.unmute(gw, "G1", "U1")
    assert u.succeeded
    b = await MODERATION.ban(gw, "G1", "U2", reason="scam")
    assert b.succeeded
    ub = await MODERATION.unban(gw, "G1", "U2")
    assert ub.succeeded
    r = await MODERATION.recall(gw, "G1", "MSG_1", reason="ad")
    assert r.succeeded
    assert len(AUDIT.recent_logs("G1", limit=20)) >= 6

    APPROVAL.update_config("G1", "enabled", "true")
    APPROVAL.update_config("G1", "default_action", "approve")
    risky_req = JoinRequest(
        join_request_id="REQ_1", member_openid="BAD_1", risk_tips="spam account"
    )
    res1 = await APPROVAL.review(gw, "G1", risky_req)
    assert res1 is not None
    assert res1.action == "reject"

    jev_risky_req = JoinRequest(join_request_id="REQ_2", member_openid="BAD_2")
    res2 = await APPROVAL.review(gw, "G1", jev_risky_req)
    assert res2 is not None
    assert res2.action == "reject"

    route, hits = MODERATION.classify_route(
        "G1", SafetyReport(violence=0.92, severity=4)
    )
    assert route == "critical_fast"
    assert hits == ["violence"]

    route_atk, _ = MODERATION.classify_route(
        "G1", SafetyReport(prompt_injection=0.88, severity=2)
    )
    assert route_atk == "attack"

    MODERATION.update_config("G1", "disabled_categories", "advertising")
    route_off, _ = MODERATION.classify_route(
        "G1", SafetyReport(advertising=0.95, severity=2)
    )
    assert route_off == "allow"

    filtered = MODERATION.filter_urls(
        "G1", ["https://github.com/org/repo", "https://spam.example/promo"]
    )
    assert filtered == ["https://spam.example/promo"]
