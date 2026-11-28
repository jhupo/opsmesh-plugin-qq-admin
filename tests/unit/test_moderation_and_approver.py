"""Unit tests for SafeguardPolicy, GroupModerator, and JoinApprover."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qq import (
    BatchRemoveMembersReturn,
    GroupBotStateReturn,
    GroupMemberInfo,
    JoinRequest,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
    ReviewQA,
    VerifyInfo,
)
from typesafe_sdk import AsyncTypeSafeClient, NoulAnswer

from qq_admin import (
    AdminConfig,
    AdminRuntime,
    AdminSettings,
    ApprovalSettings,
    EscalationRule,
    EscalationSettings,
    GroupStateStore,
    ModerationSettings,
    SafeguardPolicy,
    SafeguardSettings,
    parse_duration,
)


def _mock_gateway(
    *, bot_role: str = "admin", member_roles: dict[str, str] | None = None
) -> AsyncMock:
    gw = AsyncMock()
    gw.get_group_bot_state.return_value = GroupBotStateReturn(
        member_openid="BOT", member_role=bot_role
    )
    roles = member_roles or {}

    async def _get_member(_gid: str, mid: str) -> GroupMemberInfo:
        return GroupMemberInfo(member_openid=mid, member_role=roles.get(mid, "member"))

    gw.get_group_member.side_effect = _get_member
    gw.batch_remove_group_members.return_value = BatchRemoveMembersReturn(
        remove_members_result="ok", add_to_member_blacklist_fail_openids=[]
    )
    gw.post_group_member_blacklist.return_value = MemberBlacklistOpReturn(
        fail_openids=[]
    )
    return gw


def test_parse_duration() -> None:
    assert parse_duration(300) == 300
    assert parse_duration("10m") == 600
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400
    assert parse_duration(timedelta(minutes=5)) == 300
    with pytest.raises(ValueError, match="between 1 and"):
        parse_duration("0m")
    with pytest.raises(ValueError, match="Invalid mute duration"):
        parse_duration("bad")


@pytest.mark.anyio
async def test_safeguard_policy_8_steps_and_owner_bypass() -> None:
    cfg = AdminConfig(
        admin=AdminSettings(admins=["GLOBAL_ADM"]),
        safeguard=SafeguardSettings(
            max_mute_duration=600,
            mute_cooldown=300,
            daily_mute_limit=2,
            daily_kick_limit=1,
            protected_users=["PROT_U"],
            exempt_users={"G1": ["EXEMPT_U"]},
            auto_exempt_admins=True,
            kick_require_confirm=True,
        ),
        escalation=EscalationSettings(
            enabled=True,
            steps=[
                EscalationRule(within_hours=24, count=2, action="kick", blacklist=True),
            ],
        ),
    )
    state = GroupStateStore(cfg)
    policy = SafeguardPolicy(cfg, state)
    gw = _mock_gateway(bot_role="admin", member_roles={"GRP_ADM": "admin"})

    for target, step in [
        ("PROT_U", "protected_users"),
        ("EXEMPT_U", "exempt_users"),
        ("GLOBAL_ADM", "global_admins"),
        ("GRP_ADM", "auto_exempt_admins"),
    ]:
        verdict = await policy.verify_action(gw, "G1", target, "mute", duration=120)
        assert verdict.allowed is False
        assert verdict.step == step

    capped = await policy.verify_action(gw, "G1", "U1", "mute", duration=3600)
    assert capped.allowed is True
    assert capped.adjusted_duration == 600

    kick_blocked = await policy.verify_action(
        gw, "G1", "U1", "kick", require_confirm=True
    )
    assert kick_blocked.allowed is False
    assert kick_blocked.step == "kick_confirm"

    state.mark_member_verified("G1", "U1")
    for act in ("warn", "mute"):
        state.record_audit(
            group_id="G1",
            action=act,
            target_id="U1",
            operator_id="bot",
            reason="r",
            succeeded=True,
        )
    kick_ok = await policy.verify_action(gw, "G1", "U1", "kick", require_confirm=True)
    assert kick_ok.allowed is True
    assert kick_ok.escalated_action == "kick"
    assert kick_ok.escalate_blacklist is True

    owner_policy = SafeguardPolicy(cfg, GroupStateStore(cfg))
    owner_verdict = await owner_policy.verify_action(
        _mock_gateway(bot_role="owner"),
        "G1",
        "PROT_U",
        "mute",
        duration=7200,
    )
    assert owner_verdict.allowed is True
    assert owner_verdict.adjusted_duration == 7200


@pytest.mark.anyio
async def test_group_moderator_and_join_approver() -> None:
    now = datetime.now(UTC)
    cfg = AdminConfig(
        moderation=ModerationSettings(enabled_groups=["G1"]),
        approval=ApprovalSettings(
            enabled=True,
            default_action="approve",
            reject_on_risk_tips=True,
            use_jev_review=True,
            max_pending_seconds=300,
        ),
    )
    jev_mock = AsyncMock(spec=AsyncTypeSafeClient)
    jev_mock.system_one.side_effect = [
        SimpleNamespace(nouls={"matches": NoulAnswer(type="noul", noul=0.92)}),
        SimpleNamespace(nouls={"matches": NoulAnswer(type="noul", noul=0.08)}),
    ]
    rt = AdminRuntime(cfg, jev_client=jev_mock)
    gw = _mock_gateway(bot_role="admin")

    assert (
        await rt.moderator.warn(gw, "G1", "U1", category="ad", reason="promo")
    ).succeeded is True
    assert (
        await rt.moderator.mute(gw, "G1", "U1", duration="10m", reason="spam")
    ).succeeded is True
    assert (await rt.moderator.unmute(gw, "G1", "U1")).succeeded is True
    assert (await rt.moderator.kick(gw, "G1", "U1", blacklist=True)).succeeded is True
    assert (await rt.moderator.ban(gw, "G1", "U2")).succeeded is True
    assert (await rt.moderator.unban(gw, "G1", "U2")).succeeded is True
    assert (await rt.moderator.recall(gw, "G1", "MSG_1")).succeeded is True

    gw.get_group_join_request_list.return_value = JoinRequestListReturn(
        list=[
            JoinRequest(
                join_request_id="JR_RISK",
                member_openid="U_RISK",
                risk_tips="risk_account",
                apply_at=now,
            ),
            JoinRequest(
                join_request_id="JR_BAD",
                member_openid="U_BAD",
                apply_at=now,
                verify_info=VerifyInfo(verify_message="spam link"),
            ),
            JoinRequest(
                join_request_id="JR_STALE",
                member_openid="U_STALE",
                apply_at=now - timedelta(seconds=600),
            ),
            JoinRequest(
                join_request_id="JR_OK",
                member_openid="U_OK",
                apply_at=now,
                verify_info=VerifyInfo(
                    review_qa_list=[ReviewQA(question="why?", answer="study")]
                ),
            ),
        ],
        next_cursor="",
    )
    outcomes = await rt.approver.poll_all_groups(gw)
    assert [(o.action, o.succeeded) for o in outcomes] == [
        ("reject", True),
        ("reject", True),
        ("approve", True),
    ]
