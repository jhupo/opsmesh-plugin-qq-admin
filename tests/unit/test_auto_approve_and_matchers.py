"""Unit tests for AutoApproveService and command matcher argument parsers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    Gateway,
    GroupBotStateReturn,
    GroupJoinRequestEvent,
    JoinRequestItem,
    JoinRequestListReturn,
    Message,
    MessageSegment,
)

from qq_admin import AdminServices, AutoApproveConfig, QQAdminConfig
from qq_admin.matchers import extract_target_and_rest, parse_duration_seconds


def test_matcher_duration_and_target_parsers() -> None:
    assert parse_duration_seconds("10m") == 600
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("45s") == 45
    assert parse_duration_seconds("1d") == 86400
    assert parse_duration_seconds("invalid", default=300) == 300

    msg_with_mention = Message(
        [MessageSegment.mention_user("OPENID_1"), MessageSegment.text(" 10m spam")]
    )
    target, rest = extract_target_and_rest(msg_with_mention)
    assert target == "OPENID_1"
    assert rest == ["10m", "spam"]

    plain_target, plain_rest = extract_target_and_rest(Message("OPENID_2 5m test"))
    assert plain_target == "OPENID_2"
    assert plain_rest == ["5m", "test"]


@pytest.mark.anyio
async def test_auto_approve_rules_and_reconciliation() -> None:
    cfg = QQAdminConfig(
        auto_approve=AutoApproveConfig(
            enabled=True,
            pass_keywords=["opsmesh"],
            trusted_inviter_openids={"TRUSTED_1"},
            reject_on_risk_tips=True,
        )
    )
    services = AdminServices.create(cfg)
    gw = MagicMock(spec=Gateway)
    gw.get_group_bot_state = AsyncMock(
        return_value=GroupBotStateReturn(member_role="admin")
    )
    gw.approval_join_request = AsyncMock(return_value=None)
    gw.get_group_join_request_list = AsyncMock(
        return_value=JoinRequestListReturn(
            join_requests=[
                JoinRequestItem(
                    join_request_id="JR_KW",
                    member_openid="U_KW",
                    verify_info="hello opsmesh",
                ),
                JoinRequestItem(
                    join_request_id="JR_RISK",
                    member_openid="U_RISK",
                    risk_tips="high_risk_account",
                ),
                JoinRequestItem(
                    join_request_id="JR_MANUAL",
                    member_openid="U_MAN",
                    verify_info="just passing by",
                ),
            ]
        )
    )

    # Trusted inviter auto-approved
    ev_trusted = GroupJoinRequestEvent(
        group_openid="G1",
        join_request_id="JR_INV",
        member_openid="U_INV",
        invited_by="TRUSTED_1",
    )
    assert await services.auto_approve.handle_event(gw, ev_trusted) == "approve"

    # Reconcile pending queue
    decisions = await services.auto_approve.reconcile_pending(gw, "G1")
    assert [d for _, d in decisions] == ["approve", "decline", "manual"]
    assert gw.approval_join_request.await_count == 3
