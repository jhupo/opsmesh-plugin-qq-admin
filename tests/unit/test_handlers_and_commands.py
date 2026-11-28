"""Unit tests for Jev -> DecisionAgent -> ReplyAgent handlers and /admin commands."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from opsmesh.exception import FinishedException
import pytest
from qq import (
    GroupAddRobotEvent,
    GroupAtMessageCreateEvent,
    GroupBotStateReturn,
    GroupMemberInfo,
    GroupMessageCreateEvent,
    Message,
)
from qq.event.models import GroupAuthor

from qq_admin import (
    AdminConfig,
    AdminState,
    AutoModerateConfig,
    ExecutionReport,
    JevClient,
    JevConfig,
    LLMConfig,
    PluginRuntime,
    QQAdminConfig,
    handle_group_message_event,
    handle_group_notice_event,
    load_prompts,
)
from qq_admin.handlers import handle_admin_console


def _make_group_msg(
    *,
    group_openid: str = "G1",
    member_openid: str = "U1",
    content: str = "hello everyone",
    at_bot: bool = False,
) -> GroupMessageCreateEvent | GroupAtMessageCreateEvent:
    cls = GroupAtMessageCreateEvent if at_bot else GroupMessageCreateEvent
    return cls(
        id="MSG_1",
        group_openid=group_openid,
        content=content,
        message=Message(content),
        author=GroupAuthor(member_openid=member_openid, member_role="member"),
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
    return gw


@pytest.mark.anyio
async def test_jev_clean_chat_stays_silent_and_violation_runs_dual_agents() -> None:
    prompts = load_prompts()
    cfg = QQAdminConfig(
        admin=AdminConfig(admins=["ADMIN_1"]),
        auto_moderate=AutoModerateConfig(
            enabled=True,
            enabled_groups=["G1"],
            stop_on_violation=True,
            allow_admin_nl_control=True,
        ),
        jev=JevConfig(enabled=True, api_key="ts-test"),
        llm=LLMConfig(enabled=True, api_key="sk-test"),
    )
    sdk_mock = AsyncMock()
    runtime = PluginRuntime(
        config=cfg,
        state=AdminState(cfg),
        jev_client=JevClient(cfg.jev, sdk_client=sdk_mock),
        prompts=prompts,
    )
    gw = _mock_gateway(bot_role="admin", member_roles={"U1": "member"})

    # 1. Clean normal chat -> Jev returns none -> 100% silent
    sdk_mock.system_one.return_value = SimpleNamespace(
        answers={
            "is_prompt_injection": SimpleNamespace(noul=0.01),
            "text_violation_type": SimpleNamespace(choice="none", confidence=0.95),
            "is_friendly_banter": SimpleNamespace(noul=0.10),
            "violation_severity": SimpleNamespace(score=0.0, confidence=0.95),
        }
    )
    assert (
        await handle_group_message_event(
            gw, _make_group_msg(content="what is for lunch?"), runtime
        )
        is False
    )
    gw.send.assert_not_awaited()

    # 2. Normal member @Bot chat -> also stays 100% silent
    assert (
        await handle_group_message_event(
            gw, _make_group_msg(content="chat with me", at_bot=True), runtime
        )
        is False
    )
    gw.send.assert_not_awaited()

    # 3. Jev flags commercial_ad -> DecisionAgent executes -> ReplyAgent phrases reply
    sdk_mock.system_one.return_value = SimpleNamespace(
        answers={
            "is_prompt_injection": SimpleNamespace(noul=0.02),
            "text_violation_type": SimpleNamespace(
                choice="commercial_ad", confidence=0.93
            ),
            "is_friendly_banter": SimpleNamespace(noul=0.01),
            "violation_severity": SimpleNamespace(score=2.6, confidence=0.91),
        }
    )
    matcher = MagicMock()
    report = ExecutionReport(
        action_taken=True,
        should_reply=True,
        scenario="violation_handled",
        target_openid="U1",
        executed_actions=["recall", "mute"],
        facts_summary="recalled ad and muted 10m",
    )
    with (
        patch(
            "qq_admin.handlers.events.run_decision_agent",
            new=AsyncMock(return_value=report),
        ) as mock_dec,
        patch(
            "qq_admin.handlers.events.generate_reply",
            new=AsyncMock(return_value="Ad cleaned up and muted for 10m."),
        ) as mock_rep,
    ):
        handled = await handle_group_message_event(
            gw,
            _make_group_msg(content="buy cheap followers now"),
            runtime,
            matcher=matcher,
        )
        assert handled is True
        mock_dec.assert_awaited_once()
        mock_rep.assert_awaited_once()
        gw.send.assert_awaited_once()
        matcher.stop_propagation.assert_called_once()

    # 4. Admin @Bot NL control runs DecisionAgent(mode='admin_command') + ReplyAgent
    ev_admin = _make_group_msg(
        member_openid="ADMIN_1", content="list muted users", at_bot=True
    )
    admin_report = ExecutionReport(
        action_taken=True,
        should_reply=True,
        scenario="admin_command",
        executed_actions=["list_muted"],
        facts_summary="no muted users",
    )
    with (
        patch(
            "qq_admin.handlers.events.run_decision_agent",
            new=AsyncMock(return_value=admin_report),
        ) as mock_dec,
        patch(
            "qq_admin.handlers.events.generate_reply",
            new=AsyncMock(return_value="Nobody is muted right now."),
        ),
    ):
        assert await handle_group_message_event(gw, ev_admin, runtime) is True
        assert mock_dec.await_args.args[0].mode == "admin_command"

    # 5. GroupAddRobotEvent eagerly refreshes bot role
    notice = GroupAddRobotEvent(group_openid="G2", op_member_openid="OWNER_1")
    await handle_group_notice_event(gw, notice, runtime)
    assert runtime.state.bot_roles["G2"][0] == "admin"


@pytest.mark.anyio
async def test_admin_console_and_dynamic_permission_denied_reply() -> None:
    prompts = load_prompts()
    cfg = QQAdminConfig(
        admin=AdminConfig(admins=["ADMIN_1"], deny_response="reply"),
        auto_moderate=AutoModerateConfig(enabled_groups=["G1"]),
        llm=LLMConfig(enabled=True, api_key="sk-test"),
    )
    runtime = PluginRuntime(
        config=cfg,
        state=AdminState(cfg),
        jev_client=JevClient(cfg.jev),
        prompts=prompts,
    )
    gw = _mock_gateway(
        bot_role="admin", member_roles={"ADMIN_1": "owner", "U_NORM": "member"}
    )

    sent: list[str] = []

    async def _finish(msg: str = "") -> None:
        sent.append(msg)
        raise FinishedException

    matcher = SimpleNamespace(finish=AsyncMock(side_effect=_finish))

    # Non-admin denied reply goes through ReplyAgent with permission_denied scenario
    ev_denied = _make_group_msg(member_openid="U_NORM", content="/admin off")
    with patch(
        "qq_admin.handlers.commands.generate_reply",
        new=AsyncMock(return_value="Only owners or admins can pause moderation."),
    ) as mock_rep:
        with pytest.raises(FinishedException):
            await handle_admin_console(
                gw,
                ev_denied,
                matcher,
                runtime,
                ["off"],  # type: ignore[arg-type]
            )
        assert mock_rep.await_args.args[0].scenario == "permission_denied"
        assert sent[-1] == "Only owners or admins can pause moderation."

    # Admin runs status, perm, exempt, unexempt, log
    cfg.llm.enabled = False
    ev_admin = _make_group_msg(member_openid="ADMIN_1", content="/admin status")
    for tokens in [
        ["status"],
        ["off"],
        ["on"],
        ["exempt", "U9"],
        ["unexempt", "U9"],
        ["perm", "ADMIN_1"],
        ["log"],
    ]:
        with pytest.raises(FinishedException):
            await handle_admin_console(
                gw,
                ev_admin,
                matcher,
                runtime,
                tokens,  # type: ignore[arg-type]
            )
    assert "G1" in sent[1]
    assert "PermissionTrace" in sent[6]
