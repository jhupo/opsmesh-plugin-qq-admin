"""Bot `member_role` TTL cache and operator role (`owner`/`admin`/`member`) resolver."""

from qq import Gateway

from qq_admin.config import QQAdminConfig
from qq_admin.context import OperatorIdentity
from qq_admin.exception import BotRoleInsufficientError, PermissionDeniedError
from qq_admin.store import StateStoreProtocol
from qq_admin.typing import RoleTier, parse_role_tier, role_rank


class IdentityService:
    """Resolve and enforce dual identity requirements (Operator x Bot role)."""

    def __init__(self, config: QQAdminConfig, store: StateStoreProtocol) -> None:
        self._config = config
        self._store = store

    def resolve_operator(
        self,
        openid: str,
        *,
        member_role: str | RoleTier = RoleTier.MEMBER,
        is_superuser: bool = False,
    ) -> OperatorIdentity:
        effective_su = is_superuser or (openid in self._config.superusers)
        return OperatorIdentity(
            openid=openid,
            role=parse_role_tier(member_role),
            is_superuser=effective_su,
        )

    def ensure_operator_tier(
        self,
        operator: OperatorIdentity,
        *,
        min_tier: RoleTier = RoleTier.ADMIN,
    ) -> None:
        if role_rank(operator.effective_role) < role_rank(min_tier):
            raise PermissionDeniedError(
                f"Requires at least {min_tier.value} permission "
                f"(current role: {operator.effective_role.value})."
            )

    async def get_bot_role(
        self,
        gateway: Gateway,
        group_openid: str,
        *,
        force_refresh: bool = False,
    ) -> RoleTier:
        if not force_refresh:
            cached = await self._store.get_cached_bot_role(group_openid)
            if cached is not None:
                return cached
        state = await gateway.get_group_bot_state(group_openid)
        role = parse_role_tier(state.member_role)
        await self._store.set_cached_bot_role(
            group_openid,
            role,
            ttl_seconds=self._config.safeguard.bot_role_cache_ttl_seconds,
        )
        return role

    async def ensure_bot_admin(self, gateway: Gateway, group_openid: str) -> RoleTier:
        role = await self.get_bot_role(gateway, group_openid)
        if role_rank(role) < role_rank(RoleTier.ADMIN):
            raise BotRoleInsufficientError(
                f"Bot role in this group is {role.value}; "
                "please promote the bot to group admin first."
            )
        return role


__all__ = ["IdentityService"]
