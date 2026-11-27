"""Safeguard pipeline: protected OpenIDs, role hierarchy, quotas, and cooldowns."""

from dataclasses import dataclass

from qq_admin.config import QQAdminConfig
from qq_admin.context import AdminContext
from qq_admin.exception import (
    CooldownActiveError,
    GroupAdminDisabledError,
    QuotaExceededError,
    TargetProtectedError,
)
from qq_admin.store import StateStoreProtocol
from qq_admin.typing import RoleTier, parse_role_tier, role_rank


@dataclass(slots=True, frozen=True)
class SafeguardPass:
    """Validated safeguard result carrying remaining daily quota."""

    remaining_quota: int | None = None


class SafeguardService:
    """Six-stage safety rail guarding destructive QQ group-admin operations."""

    def __init__(self, config: QQAdminConfig, store: StateStoreProtocol) -> None:
        self._config = config
        self._store = store

    async def is_group_enabled(self, group_openid: str) -> bool:
        if group_openid in self._config.group_switch.disabled_groups:
            return False
        if group_openid in self._config.group_switch.enabled_groups:
            return True
        return await self._store.is_group_enabled(
            group_openid, default=self._config.group_switch.enabled_by_default
        )

    async def ensure_group_enabled(self, group_openid: str) -> None:
        if not await self.is_group_enabled(group_openid):
            raise GroupAdminDisabledError(
                f"Group administration is disabled for group {group_openid}."
            )

    def clamp_mute_duration(self, duration_seconds: int) -> int:
        cfg = self._config.safeguard
        return max(cfg.min_mute_seconds, min(duration_seconds, cfg.max_mute_seconds))

    def ensure_target_mutable(
        self,
        ctx: AdminContext,
        *,
        target_openid: str,
        target_role: str | RoleTier = RoleTier.MEMBER,
        bot_openid: str | None = None,
    ) -> None:
        if not target_openid:
            raise TargetProtectedError("Target member_openid must not be empty.")
        if bot_openid and target_openid == bot_openid:
            raise TargetProtectedError("Cannot moderate the bot itself.")
        if target_openid == ctx.operator.openid:
            raise TargetProtectedError("Cannot moderate yourself.")
        if target_openid in self._config.safeguard.protected_openids:
            raise TargetProtectedError(
                f"Member {target_openid} is in the protected allowlist."
            )

        target_tier = parse_role_tier(target_role)
        if target_tier == RoleTier.OWNER:
            raise TargetProtectedError("Cannot moderate or remove the group owner.")
        if not ctx.operator.is_superuser and role_rank(target_tier) >= role_rank(
            ctx.operator.effective_role
        ):
            raise TargetProtectedError(
                f"Insufficient hierarchy to moderate a {target_tier.value} member."
            )

    async def check_cooldown_and_quota(
        self,
        ctx: AdminContext,
        *,
        action_key: str,
        target_openid: str = "",
        daily_limit: int | None = None,
    ) -> SafeguardPass:
        if target_openid and not ctx.operator.is_superuser:
            ok = await self._store.acquire_target_cooldown(
                ctx.group_openid,
                target_openid,
                action_key,
                self._config.safeguard.target_cooldown_seconds,
            )
            if not ok:
                raise CooldownActiveError(
                    f"Target {target_openid} is on cooldown for {action_key}."
                )

        if daily_limit is None or ctx.operator.is_superuser:
            return SafeguardPass(remaining_quota=None)

        quota = await self._store.consume_daily_quota(
            ctx.group_openid, action_key, daily_limit
        )
        if not quota.allowed:
            raise QuotaExceededError(
                f"Daily {action_key} quota exceeded ({quota.used}/{quota.limit})."
            )
        return SafeguardPass(remaining_quota=quota.remaining)


__all__ = ["SafeguardPass", "SafeguardService"]
