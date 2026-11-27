"""Unit tests for dual permissions, six-stage safeguards, warning ladder, and store."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from qq import (
    BatchRemoveMembersReturn,
    Gateway,
    GroupBotStateReturn,
    GroupMemberInfo,
    User,
)

from qq_admin import (
    AdminContext,
    AdminServices,
    AuditConfig,
    BotRoleInsufficientError,
    CooldownActiveError,
    GroupAdminDisabledError,
    InMemoryStateStore,
    OperatorIdentity,
    PermissionDeniedError,
    QQAdminConfig,
    QuotaExceededError,
    RoleTier,
    SafeguardConfig,
    TargetProtectedError,
    ViolationType,
    WarningPolicyConfig,
)


def _mock_gateway(*, bot_role: str = "admin", target_role: str = "member") -> MagicMock:
    gw = MagicMock(spec=Gateway)
    gw.self_info = User(id="BOT_OPENID", username="OpsBot", bot=True)
    gw.get_group_bot_state = AsyncMock(
        return_value=GroupBotStateReturn(member_role=bot_role, allow_proactive_msg=True)
    )
    gw.get_group_member = AsyncMock(
        return_value=GroupMemberInfo(
            member_openid="TARGET_1", username="Target", member_role=target_role
        )
    )
    gw.set_group_members_mute = AsyncMock(return_value=None)
    gw.batch_remove_group_members = AsyncMock(
        return_value=BatchRemoveMembersReturn(removed_member_openids=["TARGET_1"])
    )
    return gw


def _ctx(
    gw: MagicMock,
    *,
    role: RoleTier = RoleTier.ADMIN,
    openid: str = "ADMIN_1",
    is_superuser: bool = False,
) -> AdminContext:
    return AdminContext(
        gateway=gw,
        group_openid="GROUP_1",
        operator=OperatorIdentity(openid=openid, role=role, is_superuser=is_superuser),
    )


@pytest.mark.anyio
async def test_dual_permission_and_target_protection_guards() -> None:
    cfg = QQAdminConfig(
        safeguard=SafeguardConfig(
            protected_openids={"VIP_1"},
            daily_mute_quota=1,
            target_cooldown_seconds=60,
        )
    )
    services = AdminServices.create(cfg)

    # 1. Regular member operator denied
    gw = _mock_gateway(bot_role="admin")
    with pytest.raises(PermissionDeniedError):
        await services.moderation.mute_member(
            _ctx(gw, role=RoleTier.MEMBER), member_openid="TARGET_1"
        )

    # 2. Bot is only member in group -> BotRoleInsufficientError
    gw_member_bot = _mock_gateway(bot_role="member")
    with pytest.raises(BotRoleInsufficientError):
        await services.moderation.mute_member(
            _ctx(gw_member_bot, role=RoleTier.OWNER), member_openid="TARGET_1"
        )

    # 3. Protected VIP cannot be muted
    services_vip = AdminServices.create(cfg)
    with pytest.raises(TargetProtectedError):
        await services_vip.moderation.mute_member(
            _ctx(gw, role=RoleTier.OWNER), member_openid="VIP_1"
        )

    # 4. Admin cannot punish owner or peer admin
    gw_owner_target = _mock_gateway(bot_role="admin", target_role="owner")
    with pytest.raises(TargetProtectedError):
        await services_vip.moderation.mute_member(
            _ctx(gw_owner_target, role=RoleTier.ADMIN), member_openid="TARGET_1"
        )

    # 5. Cooldown and daily quota enforcement
    await services_vip.moderation.mute_member(
        _ctx(gw, role=RoleTier.ADMIN), member_openid="TARGET_1", duration_seconds=120
    )
    with pytest.raises(CooldownActiveError):
        await services_vip.moderation.mute_member(
            _ctx(gw, role=RoleTier.ADMIN),
            member_openid="TARGET_1",
            duration_seconds=120,
        )
    with pytest.raises(QuotaExceededError):
        await services_vip.moderation.mute_member(
            _ctx(gw, role=RoleTier.ADMIN),
            member_openid="TARGET_2",
            duration_seconds=120,
        )

    # 6. Group disabled blocks write operations
    await services_vip.moderation.set_group_enabled(
        _ctx(gw, role=RoleTier.OWNER), enabled=False
    )
    with pytest.raises(GroupAdminDisabledError):
        await services_vip.moderation.mute_member(
            _ctx(gw, role=RoleTier.OWNER), member_openid="TARGET_3"
        )


@pytest.mark.anyio
async def test_warning_sliding_window_escalation_and_snapshot(tmp_path: Path) -> None:
    snap = tmp_path / "admin_state.json"
    cfg = QQAdminConfig(
        safeguard=SafeguardConfig(target_cooldown_seconds=0),
        warning=WarningPolicyConfig(
            window_seconds=3600,
            mute_threshold=2,
            mute_duration_seconds=300,
            kick_threshold=3,
        ),
        audit=AuditConfig(snapshot_path=str(snap)),
    )
    services = AdminServices.create(cfg)
    gw = _mock_gateway(bot_role="admin")
    ctx = _ctx(gw, role=RoleTier.OWNER)

    r1 = await services.moderation.warn_member(
        ctx, member_openid="TARGET_1", violation_type=ViolationType.SPAM, reason="r1"
    )
    assert r1.data["escalation"] == "warn_only"
    gw.set_group_members_mute.assert_not_awaited()

    r2 = await services.moderation.warn_member(
        ctx, member_openid="TARGET_1", violation_type=ViolationType.SPAM, reason="r2"
    )
    assert r2.data["escalation"] == "auto_mute"
    gw.set_group_members_mute.assert_awaited_once()

    r3 = await services.moderation.warn_member(
        ctx, member_openid="TARGET_1", violation_type=ViolationType.AD, reason="r3"
    )
    assert r3.data["escalation"] == "auto_kick"
    gw.batch_remove_group_members.assert_awaited_once()

    # Snapshot persisted and reloads cleanly
    assert snap.exists()
    reloaded = InMemoryStateStore(snapshot_path=snap)
    active = await reloaded.list_active_violations(
        "GROUP_1", "TARGET_1", window_seconds=3600
    )
    assert len(active) == 3

    cleared = await services.moderation.clear_warnings(ctx, member_openid="TARGET_1")
    assert cleared.data["cleared"] == 3
