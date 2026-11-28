"""Unit tests for declarative @command routing and EventRouter pipeline."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from openai import AsyncOpenAI
from pydantic import SecretStr
import pytest
from qq import (
    BatchRemoveMembersReturn,
    GroupAddRobotEvent,
    GroupAtMessageCreateEvent,
    GroupBotStateReturn,
    GroupMemberBlacklistReturn,
    GroupMemberInfo,
    GroupMessageCreateEvent,
    GroupRestrictChatSettingReturn,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
    Message,
)
from qq.event.models import GroupAuthor
from typesafe_sdk import AsyncTypeSafeClient, ChoiceAnswer, NoulAnswer, ScoreAnswer

from qq_admin import (
    AdminConfig,
    AdminRuntime,
    AdminSettings,
    AgentSettings,
    DecisionOutcome,
    EventRouter,
    JevSettings,
    ModerationSettings,
    dispatch_command,
)


def _msg(
    content: str, *, member_id: str = "U1", group_id: str = "G1", at_bot: bool = False
) -> GroupMessageCreateEvent | GroupAtMessageCreateEvent:
    cls = GroupAtMessageCreateEvent if at_bot else GroupMessageCreateEvent
    return cls(
        id="MSG_1",
        group_openid=group_id,
        content=content,
        message=Message(content),
        author=GroupAuthor(member_openid=member_id, member_role="member"),
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
    gw.get_group_mute_setting.return_value = GroupRestrictChatSettingReturn()
    gw.get_group_member_blacklist.return_value = GroupMemberBlacklistReturn()
    gw.get_group_join_request_list.return_value = JoinRequestListReturn()
    return gw


@pytest.mark.anyio
async def test_event_router_silence_violation_and_admin_mention() -> None:
    cfg = AdminConfig(
        admin=AdminSettings(admins=["ADMIN_1"]),
        moderation=ModerationSettings(
            enabled=True,
            enabled_groups=["G1"],
            stop_on_violation=True,
            allow_admin_nl_control=True,
        ),
        jev=JevSettings(enabled=True, api_key=SecretStr("ts-test")),
        agent=AgentSettings(enabled=True, api_key=SecretStr("sk-test")),
    )
    jev_mock = AsyncMock(spec=AsyncTypeSafeClient)
    rt = AdminRuntime(
        cfg, jev_client=jev_mock, openai_client=AsyncMock(spec=AsyncOpenAI)
    )
    router = EventRouter(rt)
    gw = _mock_gateway(bot_role="admin", member_roles={"U1": "member"})

    # 1. Normal chat & member @mention stay 100% silent
    jev_mock.system_one.return_value = SimpleNamespace(
        nouls={
            "is_prompt_injection": NoulAnswer(type="noul", noul=0.01),
            "is_friendly_banter": NoulAnswer(type="noul", noul=0.10),
        },
        choices={
            "text_violation_type": ChoiceAnswer(
                type="choice", choice="none", confidence=0.96, probabilities={}
            )
        },
        scores={
            "violation_severity": ScoreAnswer(
                type="score", score=0.0, confidence=0.96, legend={}, probabilities={}
            )
        },
    )
    assert await router.handle_message(gw, _msg("good morning")) is False
    assert await router.handle_message(gw, _msg("tell a joke", at_bot=True)) is False
    gw.send.assert_not_awaited()

    # 2. Violation routes through DecisionPlanner -> ReplyComposer
    jev_mock.system_one.return_value = SimpleNamespace(
        nouls={
            "is_prompt_injection": NoulAnswer(type="noul", noul=0.02),
            "is_friendly_banter": NoulAnswer(type="noul", noul=0.01),
        },
        choices={
            "text_violation_type": ChoiceAnswer(
                type="choice",
                choice="commercial_ad",
                confidence=0.94,
                probabilities={},
            )
        },
        scores={
            "violation_severity": ScoreAnswer(
                type="score", score=2.7, confidence=0.92, legend={}, probabilities={}
            )
        },
    )
    matcher = MagicMock()
    planned = DecisionOutcome(
        action_taken=True,
        should_reply=True,
        scenario="violation_handled",
        target_id="U1",
        executed_actions=["recall", "mute"],
        summary="recalled and muted",
    )
    with (
        patch.object(
            rt.planner, "execute", new=AsyncMock(return_value=planned)
        ) as mock_plan,
        patch.object(
            rt.composer,
            "compose",
            new=AsyncMock(return_value="Ad removed and muted for 10m."),
        ) as mock_comp,
    ):
        handled = await router.handle_message(
            gw, _msg("buy followers cheap"), matcher=matcher
        )
        assert handled is True
        mock_plan.assert_awaited_once()
        mock_comp.assert_awaited_once()
        gw.send.assert_awaited_once()
        matcher.stop_propagation.assert_called_once()

    # 3. Admin @Bot NL control routes with mode='admin_command'
    admin_planned = DecisionOutcome(
        action_taken=True,
        should_reply=True,
        scenario="admin_command",
        executed_actions=["list_muted_members"],
        summary="none muted",
    )
    with (
        patch.object(
            rt.planner, "execute", new=AsyncMock(return_value=admin_planned)
        ) as mock_plan,
        patch.object(
            rt.composer, "compose", new=AsyncMock(return_value="No one is muted.")
        ),
    ):
        assert (
            await router.handle_message(
                gw, _msg("who is muted?", member_id="ADMIN_1", at_bot=True)
            )
            is True
        )
        assert mock_plan.await_args.args[0].mode == "admin_command"

    # 4. GroupAddRobotEvent refreshes bot role
    await router.handle_notice(
        gw, GroupAddRobotEvent(group_openid="G2", op_member_openid="OWNER_1")
    )
    assert rt.state.bot_roles["G2"][0] == "admin"


@pytest.mark.anyio
async def test_all_declarative_command_routes() -> None:
    cfg = AdminConfig(
        admin=AdminSettings(admins=["ADMIN_1"], deny_response="reply"),
        moderation=ModerationSettings(enabled_groups=["G1"]),
    )
    rt = AdminRuntime(cfg)
    gw = _mock_gateway(
        bot_role="admin", member_roles={"ADMIN_1": "owner", "U_MEM": "member"}
    )

    # Unauthorized user receives denial reply
    matched, denied = await dispatch_command(
        gw, _msg("/admin off", member_id="U_MEM"), rt
    )
    assert matched is True
    assert denied is not None

    # Bad syntax returns clean usage hint
    matched, usage = await dispatch_command(gw, _msg("/mute", member_id="ADMIN_1"), rt)
    assert matched is True
    assert usage == "Usage: /mute <member_openid> <10m|1h|600> [reason]"

    # Execute console, moderation, and query commands cleanly
    for cmd_text in [
        "/admin status",
        "/admin off",
        "/admin on",
        "/admin exempt @U9",
        "/admin unexempt U9",
        "/admin perm ADMIN_1",
        "/warn @U1 spam flood",
        "/mute @U1 10m spam",
        "/admin undo U1",
        "/kick U2 --ban ad",
        "/ban U3 scam",
        "/unban U3",
        "/recall MSG_99",
        "/approve U4 JR_1",
        "/reject U5 JR_2 spam",
        "/shutlist",
        "/blacklist",
        "/requests",
        "/member U1",
        "/admin log 5",
    ]:
        matched, reply = await dispatch_command(
            gw, _msg(cmd_text, member_id="ADMIN_1"), rt
        )
        assert matched is True
        assert reply is not None
