"""Tests for direct commands (/admin, actions, queries) and messages/group_events."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    BlacklistUser,
    GroupAddRobotEvent,
    GroupBotStateReturn,
    GroupDelRobotEvent,
    GroupJoinRequestEvent,
    GroupMemberAddEvent,
    GroupMemberBlacklistReturn,
    GroupMemberInfo,
    GroupMemberRemoveEvent,
    GroupMessageCreateEvent,
    GroupRestrictChatSettingReturn,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
)
from qq.event import GroupAuthor

from qq_admin import (
    ACTION_COMMANDS,
    ServiceManager,
    handle_group_event,
    handle_group_message,
    run_action,
    run_admin,
    run_query,
)


def _msg(
    content: str, *, group_id: str = "G1", user_id: str = "ADMIN_1"
) -> GroupMessageCreateEvent:
    return GroupMessageCreateEvent(
        id="M_1",
        content=content,
        group_openid=group_id,
        author=GroupAuthor(member_openid=user_id),
    )


def _gateway(*, bot_role: str = "admin", roles: dict[str, str] | None = None):
    role_map = roles or {"ADMIN_1": "owner", "MOD_1": "admin", "U1": "member"}
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
    gw.get_group_mute_setting = AsyncMock(return_value=GroupRestrictChatSettingReturn())
    gw.get_group_member_blacklist = AsyncMock(
        return_value=GroupMemberBlacklistReturn(
            users=[BlacklistUser(member_openid="BAD_1", username="bad")]
        )
    )
    gw.get_group_join_request_list = AsyncMock(return_value=JoinRequestListReturn())
    gw.download_attachment = AsyncMock(return_value=b"img")
    return gw


@pytest.mark.anyio
async def test_admin_online_commands_actions_and_queries() -> None:
    manager = ServiceManager()
    manager.identity.update_config("G1", "admins", "ADMIN_1")
    gw = _gateway()

    # Unauthorized member is silently ignored by default
    assert await run_admin(gw, _msg("/admin on", user_id="U1"), manager) is None

    # /admin on -> enables group G1
    on_reply = await run_admin(gw, _msg("/admin on"), manager)
    assert on_reply
    assert manager.is_group_enabled("G1")

    # /admin config set & get
    set_reply = await run_admin(
        gw, _msg("/admin config set safeguard.max_mute_duration 1200"), manager
    )
    assert set_reply
    assert manager.safeguard.config("G1").max_mute_duration == 1200
    get_reply = await run_admin(
        gw, _msg("/admin config get safeguard.max_mute_duration"), manager
    )
    assert get_reply == "safeguard.max_mute_duration = 1200"

    # /admin session mode & reset
    sess_reply = await run_admin(gw, _msg("/admin session mode shared"), manager)
    assert sess_reply
    assert manager.decision_agent.session_mode("G1") == "shared"
    assert await run_admin(gw, _msg("/admin session reset"), manager)

    # /admin status, perm, exempt, unexempt, log, undo
    assert await run_admin(gw, _msg("/admin status"), manager)
    assert "allowed=True" in (
        await run_admin(gw, _msg("/admin perm @ADMIN_1"), manager) or ""
    )
    assert await run_admin(gw, _msg("/admin exempt @U1"), manager)
    assert "U1" in manager.safeguard.config("G1").exempt_users
    assert await run_admin(gw, _msg("/admin unexempt @U1"), manager)
    assert "U1" not in manager.safeguard.config("G1").exempt_users
    assert await run_admin(gw, _msg("/admin undo @U1"), manager)
    assert await run_admin(gw, _msg("/admin log 5"), manager)

    # Action commands
    by_name = {c.name: c for c in ACTION_COMMANDS}
    assert await run_action(by_name["warn"], gw, _msg("/warn @U1 spam flood"), manager)
    assert await run_action(by_name["mute"], gw, _msg("/mute @U1 5m flood"), manager)
    assert await run_action(by_name["unmute"], gw, _msg("/unmute @U1"), manager)
    assert await run_action(by_name["kick"], gw, _msg("/kick @U1 ad"), manager)
    assert await run_action(by_name["ban"], gw, _msg("/ban @U1 scam"), manager)
    assert await run_action(by_name["unban"], gw, _msg("/unban @U1"), manager)
    assert await run_action(by_name["recall"], gw, _msg("/recall MSG_9 ad"), manager)
    assert await run_action(by_name["approve"], gw, _msg("/approve U9 REQ_9"), manager)
    assert await run_action(by_name["reject"], gw, _msg("/reject U9 bad"), manager)

    # Query commands
    assert await run_query("shutlist", gw, _msg("/shutlist"), manager)
    assert "BAD_1" in (
        await run_query("blacklist", gw, _msg("/blacklist"), manager) or ""
    )
    assert await run_query("requests", gw, _msg("/requests"), manager)
    assert "role=member" in (
        await run_query("member", gw, _msg("/member @U1"), manager) or ""
    )

    # /admin off -> disables group G1
    assert await run_admin(gw, _msg("/admin off"), manager)
    assert not manager.is_group_enabled("G1")


@pytest.mark.anyio
async def test_group_message_and_lifecycle_events() -> None:
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock(
        return_value=SimpleNamespace(
            nouls={
                "injection": SimpleNamespace(noul=0.01),
                "banter": SimpleNamespace(noul=0.02),
            },
            choices={
                "text_violation": SimpleNamespace(
                    choice="commercial_ad", confidence=0.95
                )
            },
            scores={"severity": SimpleNamespace(score=2.0, confidence=0.92)},
        )
    )
    manager = ServiceManager(jev_client=fake_jev)
    gw = _gateway()

    # Disabled group -> completely silent
    handled, reply = await handle_group_message(
        gw, _msg("buy ad now", user_id="U1"), manager
    )
    assert not handled
    assert reply is None

    # Enable group -> Jev catches violation and enforces without agent
    manager.set_group_enabled("G1", True)
    handled, reply = await handle_group_message(
        gw, _msg("buy ad now", user_id="U1"), manager
    )
    assert handled is True
    assert reply is not None
    gw.delete_group_message.assert_awaited_once()
    gw.set_group_members_mute.assert_awaited_once()

    # Lifecycle events: bot join, join request, member join, member leave, bot leave
    await handle_group_event(gw, GroupAddRobotEvent(group_openid="G1"), manager)

    manager.approval.update_config("G1", "enabled", "true")
    manager.approval.update_config("G1", "default_action", "approve")
    await handle_group_event(
        gw,
        GroupJoinRequestEvent(
            group_openid="G1",
            join_request_id="JR_1",
            member_openid="NEW_1",
            risk_tips="high risk",
        ),
        manager,
    )
    gw.approval_join_request.assert_awaited_once()

    manager.moderation.update_config("G1", "welcome_new_members", "true")
    welcome = await handle_group_event(
        gw, GroupMemberAddEvent(group_openid="G1", member_openid="NEW_2"), manager
    )
    assert welcome
    assert "NEW_2" in welcome

    await handle_group_event(
        gw, GroupMemberRemoveEvent(group_openid="G1", member_openid="NEW_2"), manager
    )
    await handle_group_event(gw, GroupDelRobotEvent(group_openid="G1"), manager)
    assert manager.audit.recent_logs("G1") == []
