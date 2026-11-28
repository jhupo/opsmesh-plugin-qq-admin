"""Tests for direct on_command handlers and messages/group_events."""

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
    APPROVAL,
    AUDIT,
    IDENTITY,
    MANAGER,
    MODERATION,
    SAFEGUARD,
    Config,
)
from qq_admin.commands import actions, admin, queries
from qq_admin.messages import process_group_event, process_group_message


class _Finished(Exception):
    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply


class _FakeMatcher:
    async def finish(self, message: str | None = None) -> None:
        raise _Finished(message)


async def _invoke(handler, gateway, event) -> str | None:
    try:
        await handler(gateway, event, _FakeMatcher())
    except _Finished as fin:
        return fin.reply
    return None


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
async def test_direct_on_command_handlers() -> None:
    IDENTITY.update_config("G1", "admins", "ADMIN_1")
    gw = _gateway()

    assert (
        await _invoke(admin.handle_admin_on, gw, _msg("/admin on", user_id="U1"))
        is None
    )

    on_reply = await _invoke(admin.handle_admin_on, gw, _msg("/admin on"))
    assert on_reply
    assert MANAGER.is_group_enabled("G1")

    set_reply = await _invoke(
        admin.handle_admin_config,
        gw,
        _msg("/admin config set safeguard.max_mute_duration 1200"),
    )
    assert set_reply
    assert SAFEGUARD.config("G1").max_mute_duration == 1200

    get_reply = await _invoke(
        admin.handle_admin_config,
        gw,
        _msg("/admin config get safeguard.max_mute_duration"),
    )
    assert get_reply == "safeguard.max_mute_duration = 1200"

    assert await _invoke(admin.handle_admin_status, gw, _msg("/admin status"))
    perm_reply = await _invoke(
        admin.handle_admin_perm, gw, _msg("/admin perm @ADMIN_1")
    )
    assert perm_reply
    assert "admin=True" in perm_reply

    assert await _invoke(admin.handle_admin_exempt, gw, _msg("/admin exempt @U1"))
    assert "U1" in SAFEGUARD.config("G1").exempt_users
    assert await _invoke(admin.handle_admin_unexempt, gw, _msg("/admin unexempt @U1"))
    assert "U1" not in SAFEGUARD.config("G1").exempt_users
    assert await _invoke(admin.handle_admin_undo, gw, _msg("/admin undo @U1"))
    assert await _invoke(admin.handle_admin_log, gw, _msg("/admin log 5"))

    assert await _invoke(actions.handle_warn, gw, _msg("/warn @U1 spam flood"))
    assert await _invoke(actions.handle_mute, gw, _msg("/mute @U1 5m flood"))
    assert await _invoke(actions.handle_unmute, gw, _msg("/unmute @U1"))
    assert await _invoke(actions.handle_kick, gw, _msg("/kick @U1 ad"))
    assert await _invoke(actions.handle_ban, gw, _msg("/ban @U1 scam"))
    assert await _invoke(actions.handle_unban, gw, _msg("/unban @U1"))
    assert await _invoke(actions.handle_recall, gw, _msg("/recall MSG_9 ad"))
    assert await _invoke(actions.handle_approve, gw, _msg("/approve U9 REQ_9"))
    assert await _invoke(actions.handle_reject, gw, _msg("/reject U9 bad"))

    assert await _invoke(queries.handle_shutlist, gw, _msg("/shutlist"))
    bl_reply = await _invoke(queries.handle_blacklist, gw, _msg("/blacklist"))
    assert bl_reply
    assert "BAD_1" in bl_reply
    assert await _invoke(queries.handle_requests, gw, _msg("/requests"))
    mem_reply = await _invoke(queries.handle_member, gw, _msg("/member @U1"))
    assert mem_reply
    assert "role=member" in mem_reply

    assert await _invoke(admin.handle_admin_off, gw, _msg("/admin off"))
    assert not MANAGER.is_group_enabled("G1")


@pytest.mark.anyio
async def test_group_message_admin_skip_and_lifecycle_events() -> None:
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock(
        return_value=SimpleNamespace(
            nouls={
                "advertising": SimpleNamespace(noul=0.95),
                "prompt_injection": SimpleNamespace(noul=0.01),
            },
            scores={"severity": SimpleNamespace(score=2.0, confidence=0.92)},
        )
    )
    MANAGER.setup(Config(), jev_client=fake_jev)
    gw = _gateway()

    handled, reply = await process_group_message(gw, _msg("buy ad now", user_id="U1"))
    assert not handled
    assert reply is None

    MANAGER.set_group_enabled("G1", True)
    admin_handled, admin_reply = await process_group_message(
        gw, _msg("buy ad now", user_id="MOD_1")
    )
    assert not admin_handled
    assert admin_reply is None

    handled, reply = await process_group_message(gw, _msg("buy ad now", user_id="U1"))
    assert handled is True
    assert reply is not None
    gw.delete_group_message.assert_awaited_once()
    gw.set_group_members_mute.assert_awaited_once()

    await process_group_event(gw, GroupAddRobotEvent(group_openid="G1"))

    APPROVAL.update_config("G1", "enabled", "true")
    APPROVAL.update_config("G1", "default_action", "approve")
    await process_group_event(
        gw,
        GroupJoinRequestEvent(
            group_openid="G1",
            join_request_id="JR_1",
            member_openid="NEW_1",
            risk_tips="high risk",
        ),
    )
    gw.approval_join_request.assert_awaited_once()

    MODERATION.update_config("G1", "welcome_new_members", "true")
    welcome = await process_group_event(
        gw, GroupMemberAddEvent(group_openid="G1", member_openid="NEW_2")
    )
    assert welcome
    assert "NEW_2" in welcome

    await process_group_event(
        gw, GroupMemberRemoveEvent(group_openid="G1", member_openid="NEW_2")
    )
    await process_group_event(gw, GroupDelRobotEvent(group_openid="G1"))
    assert AUDIT.recent_logs("G1") == []
