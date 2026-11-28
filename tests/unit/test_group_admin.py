"""Comprehensive unit tests for QQGroupAdmin, QQGroupScope, pagination, and Depends."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    BatchRemoveMembersReturn,
    BlacklistUser,
    C2CMessageCreateEvent,
    Gateway,
    GlobalMuteRule,
    GroupAtMessageCreateEvent,
    GroupBotStateReturn,
    GroupInfoReturn,
    GroupJoinRequestEvent,
    GroupMember,
    GroupMemberBlacklistReturn,
    GroupMemberInfo,
    GroupMembersReturn,
    GroupRestrictChatSettingReturn,
    JoinRequest,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
    MemberMuteState,
    PostGroupMembersReturn,
)

from qq_admin import (
    BotNotAdminError,
    GroupTargetRequiredError,
    HierarchyError,
    QQGroupAdmin,
    can_manage_member,
    ensure_can_manage,
    extract_group_openid,
    get_current_group,
    get_group_admin,
    parse_mute_duration,
)


def test_duration_and_hierarchy_helpers() -> None:
    assert parse_mute_duration(300) == timedelta(seconds=300)
    assert parse_mute_duration("10m") == timedelta(minutes=10)
    assert parse_mute_duration("2h") == timedelta(hours=2)
    assert parse_mute_duration("1d") == timedelta(days=1)
    now = datetime.now(tz=UTC)
    assert parse_mute_duration(now) == now

    with pytest.raises(ValueError, match="positive"):
        parse_mute_duration(0)
    with pytest.raises(ValueError, match="Invalid"):
        parse_mute_duration("forever")

    assert can_manage_member("owner", "admin")
    assert can_manage_member("owner", "member")
    assert can_manage_member("admin", "member")
    assert not can_manage_member("admin", "admin")
    assert not can_manage_member("admin", "owner")
    assert not can_manage_member("owner", "owner")

    ensure_can_manage("admin", "member")
    with pytest.raises(HierarchyError):
        ensure_can_manage("admin", "owner")


def test_extract_group_openid_and_depends_helpers() -> None:
    gw = MagicMock(spec=Gateway)
    msg_ev = GroupAtMessageCreateEvent(group_openid="G_MSG")
    notice_ev = GroupJoinRequestEvent(group_openid="G_NOTICE")
    c2c_ev = C2CMessageCreateEvent()

    assert extract_group_openid(msg_ev) == "G_MSG"
    assert extract_group_openid(notice_ev) == "G_NOTICE"
    with pytest.raises(GroupTargetRequiredError):
        extract_group_openid(c2c_ev)

    admin = get_group_admin(gw)
    assert admin.gateway is gw
    scope = get_current_group(gw, msg_ev)
    assert scope.group_openid == "G_MSG"
    assert scope.gateway is gw


@pytest.mark.anyio
async def test_qq_group_admin_and_scope_all_6_domains() -> None:
    gw = MagicMock(spec=Gateway)
    gw.get_group_info = AsyncMock(
        return_value=GroupInfoReturn(
            group_openid="G1", group_name="Ops", group_member_num=25
        )
    )
    gw.get_group_bot_state = AsyncMock(
        return_value=GroupBotStateReturn(
            member_openid="BOT", member_role="admin", allow_proactive_msg=True
        )
    )
    gw.get_group_member = AsyncMock(
        return_value=GroupMemberInfo(
            member_openid="M1", username="Alice", member_role="member", bot=False
        )
    )
    gw.get_group_members = AsyncMock(
        side_effect=[
            GroupMembersReturn(
                members=[GroupMemberInfo(member_openid="M1", bot=False)],
                next_cursor="CUR_2",
            ),
            GroupMembersReturn(
                members=[GroupMemberInfo(member_openid="M2", bot=False)],
                next_cursor=None,
            ),
        ]
    )
    gw.post_group_members = AsyncMock(
        return_value=PostGroupMembersReturn(
            members=[GroupMember(member_openid="M1")], next_index=0
        )
    )
    gw.get_group_mute_setting = AsyncMock(
        return_value=GroupRestrictChatSettingReturn(
            global_rule=GlobalMuteRule(mode="none"),
            members=[MemberMuteState(member_openid="M1", username="Alice")],
        )
    )
    gw.set_group_members_mute = AsyncMock(return_value=None)
    gw.batch_remove_group_members = AsyncMock(
        return_value=BatchRemoveMembersReturn(remove_members_result="ok")
    )
    gw.get_group_member_blacklist = AsyncMock(
        side_effect=[
            GroupMemberBlacklistReturn(
                users=[BlacklistUser(member_openid="B1")], next_cursor="BC_2"
            ),
            GroupMemberBlacklistReturn(
                users=[BlacklistUser(member_openid="B2")], next_cursor=None
            ),
        ]
    )
    gw.post_group_member_blacklist = AsyncMock(
        return_value=MemberBlacklistOpReturn(fail_openids=[])
    )
    gw.get_group_join_request_list = AsyncMock(
        side_effect=[
            JoinRequestListReturn(
                list=[JoinRequest(join_request_id="JR1", member_openid="J1")],
                next_cursor="JC_2",
            ),
            JoinRequestListReturn(
                list=[JoinRequest(join_request_id="JR2", member_openid="J2")],
                next_cursor="",
            ),
        ]
    )
    gw.approval_join_request = AsyncMock(return_value=None)
    gw.delete_group_message = AsyncMock(return_value=None)

    admin = QQGroupAdmin(gw)
    scope = admin.group("G1")

    # 1. Info & Bot State
    info = await scope.get_info()
    assert info.group_member_num == 25
    assert await scope.is_bot_admin() is True
    assert (await scope.ensure_bot_admin()).member_role == "admin"

    gw.get_group_bot_state.return_value = GroupBotStateReturn(member_role="member")
    assert await scope.is_bot_admin() is False
    with pytest.raises(BotNotAdminError):
        await scope.ensure_bot_admin()

    # 2. Members & Auto-Pagination
    assert (await scope.get_member("M1")).username == "Alice"
    assert len((await scope.list_members_by_index(limit=10)).members) == 1
    all_members = await scope.get_all_members()
    assert [m.member_openid for m in all_members] == ["M1", "M2"]

    # 3. Mute & Unmute
    assert (await scope.get_global_mute_rule()).mode == "none"
    assert len(await scope.list_muted_members()) == 1
    await scope.mute("M1", "15m")
    mute_call_items = gw.set_group_members_mute.await_args_list[-1].args[1]
    assert mute_call_items[0].op == "add"
    assert mute_call_items[0].mute_expire_at is not None
    await scope.unmute("M1")
    unmute_call_items = gw.set_group_members_mute.await_args_list[-1].args[1]
    assert unmute_call_items[0].op == "del"

    # 4. Kick
    kick_res = await scope.kick("M1", add_to_blacklist=True)
    assert kick_res.remove_members_result == "ok"

    # 5. Blacklist & Auto-Pagination
    all_banned = await scope.get_all_blacklist()
    assert [u.member_openid for u in all_banned] == ["B1", "B2"]
    assert (await scope.ban("B3")).fail_openids == []
    assert (await scope.unban("B3")).fail_openids == []

    # 6. Join Requests & Recall
    all_reqs = await scope.get_all_join_requests()
    assert [r.join_request_id for r in all_reqs] == ["JR1", "JR2"]
    await scope.approve_join("J1", join_request_id="JR1")
    await scope.reject_join(
        "J2", join_request_id="JR2", reason="spam", add_to_blacklist=True
    )
    await scope.recall("MSG_100")
    gw.delete_group_message.assert_awaited_once_with("G1", "MSG_100")
