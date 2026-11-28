"""Unit tests for all 18 standalone public async function APIs."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    BatchRemoveMembersReturn,
    Gateway,
    GroupBotStateReturn,
    GroupInfoReturn,
    GroupMemberBlacklistReturn,
    GroupMemberInfo,
    GroupMembersReturn,
    GroupRestrictChatSettingReturn,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
    User,
)

from qq_admin import (
    AdminContext,
    AdminServices,
    OperatorIdentity,
    RoleTier,
    add_blacklist,
    approve_join_request,
    clear_warnings,
    decline_join_request,
    get_audit_log,
    get_bot_state,
    get_group_info,
    get_member,
    get_mute_setting,
    kick_member,
    list_blacklist,
    list_join_requests,
    list_members,
    mute_member,
    recall_message,
    remove_blacklist,
    set_group_enabled,
    set_services,
    unmute_member,
    warn_member,
)


def _mock_full_gateway() -> MagicMock:
    gw = MagicMock(spec=Gateway)
    gw.self_info = User(id="BOT_1", username="OpsBot", bot=True)
    gw.get_group_info = AsyncMock(
        return_value=GroupInfoReturn(
            group_openid="G1", group_name="Ops", member_count=10
        )
    )
    gw.get_group_bot_state = AsyncMock(
        return_value=GroupBotStateReturn(member_role="admin", allow_proactive_msg=True)
    )
    gw.get_group_member = AsyncMock(
        return_value=GroupMemberInfo(
            member_openid="U1", username="Bob", member_role="member"
        )
    )
    gw.get_group_members = AsyncMock(return_value=GroupMembersReturn(members=[]))
    gw.get_group_mute_setting = AsyncMock(
        return_value=GroupRestrictChatSettingReturn(muted_members=[])
    )
    gw.set_group_members_mute = AsyncMock(return_value=None)
    gw.batch_remove_group_members = AsyncMock(
        return_value=BatchRemoveMembersReturn(removed_member_openids=["U1"])
    )
    gw.delete_group_message = AsyncMock(return_value=None)
    gw.get_group_member_blacklist = AsyncMock(
        return_value=GroupMemberBlacklistReturn(members=[])
    )
    gw.post_group_member_blacklist = AsyncMock(
        return_value=MemberBlacklistOpReturn(success_member_openids=["U1"])
    )
    gw.get_group_join_request_list = AsyncMock(
        return_value=JoinRequestListReturn(join_requests=[])
    )
    gw.approval_join_request = AsyncMock(return_value=None)
    return gw


@pytest.mark.anyio
async def test_all_18_standalone_public_async_apis() -> None:
    services = AdminServices.create()
    set_services(services)
    gw = _mock_full_gateway()
    ctx = AdminContext(
        gateway=gw,
        group_openid="G1",
        operator=OperatorIdentity(
            openid="OWNER_1", role=RoleTier.OWNER, is_superuser=True
        ),
    )

    assert (await set_group_enabled(ctx, enabled=True)).data["enabled"] is True
    assert (await get_group_info(ctx)).action == "get_group_info"
    assert (await get_bot_state(ctx)).action == "get_bot_state"
    assert (await get_member(ctx, member_openid="U1")).action == "get_member"
    assert (await list_members(ctx)).action == "list_members"
    assert (await get_mute_setting(ctx)).action == "get_mute_setting"
    assert (
        await mute_member(ctx, member_openid="U1", duration_seconds=300, reason="spam")
    ).data["duration_seconds"] == 300
    assert (await unmute_member(ctx, member_openid="U1")).action == "unmute_member"
    assert (
        await warn_member(ctx, member_openid="U1", reason="ad")
    ).action == "warn_member"
    assert (await clear_warnings(ctx, member_openid="U1")).data["cleared"] == 1
    assert (await kick_member(ctx, member_openid="U1")).action == "kick_member"
    assert (await recall_message(ctx, message_id="MSG_1")).action == "recall_message"
    assert (await list_blacklist(ctx)).action == "list_blacklist"
    assert (await add_blacklist(ctx, member_openids=["U1"])).action == "add_blacklist"
    assert (
        await remove_blacklist(ctx, member_openids=["U1"])
    ).action == "remove_blacklist"
    assert (await list_join_requests(ctx)).action == "list_join_requests"
    assert (
        await approve_join_request(ctx, member_openid="U2", join_request_id="JR1")
    ).action == "approve_join_request"
    assert (
        await decline_join_request(
            ctx, member_openid="U3", join_request_id="JR2", reject_reason="nope"
        )
    ).action == "decline_join_request"

    audit = await get_audit_log(ctx, limit=50)
    assert len(audit.data["records"]) >= 10
