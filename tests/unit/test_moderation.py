"""Unit tests for moderation guardrails, direct QQ v2 actions, and join review."""

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

from qq_admin import (
    AdminConfig,
    AdminState,
    AutoApproveConfig,
    AutoModerateConfig,
    EscalationConfig,
    EscalationStep,
    JevClient,
    JevConfig,
    PluginRuntime,
    QQAdminConfig,
    SafeguardConfig,
    ban_member,
    check_action_guard,
    enforce_escalation_violation,
    evaluate_command_permission,
    kick_member,
    load_prompts,
    mute_member,
    parse_mute_duration,
    recall_message,
    scan_join_requests_once,
    unban_member,
    unmute_member,
    warn_member,
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


def test_parse_mute_duration_variants() -> None:
    assert parse_mute_duration(300) == 300
    assert parse_mute_duration("10m") == 600
    assert parse_mute_duration("2h") == 7200
    assert parse_mute_duration("1d") == 86400
    assert parse_mute_duration(timedelta(minutes=5)) == 300
    with pytest.raises(ValueError, match="between 1 and"):
        parse_mute_duration("0m")
    with pytest.raises(ValueError, match="Invalid mute duration"):
        parse_mute_duration("invalid")


@pytest.mark.anyio
async def test_role_aware_8_step_guard_and_owner_bypass() -> None:
    cfg = QQAdminConfig(
        admin=AdminConfig(admins=["GLOBAL_ADMIN"]),
        safeguard=SafeguardConfig(
            max_mute_duration=600,
            mute_cooldown=300,
            daily_mute_limit=2,
            daily_kick_limit=1,
            protected_users=["PROTECTED_U"],
            exempt_users={"G1": ["EXEMPT_U"]},
            auto_exempt_admins=True,
            kick_require_member_check=True,
        ),
        escalation=EscalationConfig(
            enabled=True,
            steps=[
                EscalationStep(
                    within_hours=24, count=1, action="mute", mute_seconds=300
                ),
                EscalationStep(
                    within_hours=24,
                    count=2,
                    action="kick",
                    mute_seconds=600,
                    add_to_blacklist=True,
                ),
            ],
        ),
    )
    state = AdminState(cfg)
    gw_admin = _mock_gateway(
        bot_role="admin", member_roles={"GROUP_ADM": "admin", "U1": "member"}
    )

    for target, expected_step in [
        ("PROTECTED_U", "protected_users"),
        ("EXEMPT_U", "exempt_users"),
        ("GLOBAL_ADMIN", "global_admins"),
        ("GROUP_ADM", "auto_exempt_admins"),
    ]:
        res = await check_action_guard(
            gw_admin,
            cfg,
            state,
            group_openid="G1",
            target_openid=target,
            action="mute",
            duration_seconds=120,
        )
        assert res.allowed is False
        assert res.step == expected_step

    res_ok = await check_action_guard(
        gw_admin,
        cfg,
        state,
        group_openid="G1",
        target_openid="U1",
        action="mute",
        duration_seconds=7200,
    )
    assert res_ok.allowed is True
    assert res_ok.adjusted_duration == 600

    res_kick_block = await check_action_guard(
        gw_admin,
        cfg,
        state,
        group_openid="G1",
        target_openid="U1",
        action="kick",
        require_member_check=True,
    )
    assert res_kick_block.allowed is False
    assert res_kick_block.step == "kick_member_check"

    state.mark_member_checked("G1", "U1")
    for act in ("warn", "mute"):
        state.record_op(
            group_openid="G1",
            action=act,
            target_openid="U1",
            operator_openid="bot",
            reason="r",
            success=True,
        )
    res_kick_ok = await check_action_guard(
        gw_admin,
        cfg,
        state,
        group_openid="G1",
        target_openid="U1",
        action="kick",
        require_member_check=True,
    )
    assert res_kick_ok.allowed is True
    assert res_kick_ok.escalated_action == "kick"
    assert res_kick_ok.escalate_blacklist is True

    gw_owner = _mock_gateway(bot_role="owner")
    res_owner = await check_action_guard(
        gw_owner,
        cfg,
        AdminState(cfg),
        group_openid="G1",
        target_openid="PROTECTED_U",
        action="mute",
        duration_seconds=7200,
    )
    assert res_owner.allowed is True
    assert res_owner.adjusted_duration == 7200

    allowed, trace = await evaluate_command_permission(
        gw_admin, cfg, state, "G1", "GROUP_ADM", minimum_role="admin"
    )
    assert allowed is True
    assert "ALLOW" in trace.format_text()


@pytest.mark.anyio
async def test_direct_v2_actions_and_jev_join_review() -> None:
    now = datetime.now(UTC)
    prompts = load_prompts()
    cfg = QQAdminConfig(
        auto_moderate=AutoModerateConfig(enabled_groups=["G1"]),
        jev=JevConfig(enabled=True, api_key="ts-test"),
        auto_approve=AutoApproveConfig(
            enabled=True,
            default_action="approve",
            reject_on_risk_tips=True,
            use_jev_review=True,
            max_pending_seconds=300,
        ),
    )
    sdk_mock = AsyncMock()
    sdk_mock.system_one.side_effect = [
        SimpleNamespace(answers={"matches": SimpleNamespace(noul=0.92)}),
        SimpleNamespace(answers={"matches": SimpleNamespace(noul=0.10)}),
    ]
    runtime = PluginRuntime(
        config=cfg,
        state=AdminState(cfg),
        jev_client=JevClient(cfg.jev, sdk_client=sdk_mock),
        prompts=prompts,
    )
    gw = _mock_gateway(bot_role="admin")

    assert (
        await warn_member(
            gw,
            runtime,
            group_openid="G1",
            member_openid="U1",
            category="ad",
            reason="ad",
        )
    ).ok is True
    assert (
        await mute_member(
            gw, runtime, group_openid="G1", member_openid="U1", duration="10m"
        )
    ).ok is True
    assert (
        await unmute_member(gw, runtime, group_openid="G1", member_openid="U1")
    ).ok is True
    assert (
        await kick_member(
            gw, runtime, group_openid="G1", member_openid="U1", add_to_blacklist=True
        )
    ).ok is True
    assert (
        await ban_member(gw, runtime, group_openid="G1", member_openid="U2")
    ).ok is True
    assert (
        await unban_member(gw, runtime, group_openid="G1", member_openid="U2")
    ).ok is True
    assert (
        await recall_message(gw, runtime, group_openid="G1", message_id="M1")
    ).ok is True

    gw_owner = _mock_gateway(bot_role="owner")
    outcomes = await enforce_escalation_violation(
        gw_owner,
        runtime,
        group_openid="G1",
        member_openid="U3",
        message_id="M2",
        category="ad",
        severity="severe",
        reason="scam",
    )
    assert [o.action for o in outcomes] == ["recall", "kick"]

    gw.get_group_join_request_list.return_value = JoinRequestListReturn(
        list=[
            JoinRequest(
                join_request_id="JR_RISK",
                member_openid="U_RISK",
                risk_tips="high_risk",
                apply_at=now,
            ),
            JoinRequest(
                join_request_id="JR_JEV_BAD",
                member_openid="U_BAD",
                apply_at=now,
                verify_info=VerifyInfo(verify_message="spam promo"),
            ),
            JoinRequest(
                join_request_id="JR_OLD",
                member_openid="U_OLD",
                apply_at=now - timedelta(seconds=600),
            ),
            JoinRequest(
                join_request_id="JR_OK",
                member_openid="U_OK",
                apply_at=now,
                verify_info=VerifyInfo(
                    review_qa_list=[ReviewQA(question="why?", answer="learning")]
                ),
            ),
        ],
        next_cursor="",
    )
    join_results = await scan_join_requests_once(gw, runtime)
    assert [(r.action, r.ok) for r in join_results] == [
        ("reject", True),
        ("reject", True),
        ("approve", True),
    ]
