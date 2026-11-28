"""Multi-group & multi-bot identity cache, admin checks, and OpsMesh Permission."""

from dataclasses import dataclass
import time
from typing import Literal

from opsmesh.permission import Permission
from pydantic import BaseModel, Field
from qq import Gateway, GroupMessageEvent

from qq_admin.exception import ConfigError
from qq_admin.store import CONFIG_STORE, ConfigStore, parse_field_value


class IdentityConfig(BaseModel):
    """Role cache TTLs and configured admin allowlist."""

    admins: list[str] = Field(
        default_factory=list, description="Admin member_openid allowlist."
    )
    deny_response: Literal["silent", "reply"] = Field(
        default="silent",
        description="Behavior when a non-admin invokes a management command.",
    )
    role_cache_ttl_seconds: int = Field(default=600, ge=30)
    bot_role_refresh_seconds: int = Field(default=300, ge=30)
    sender_role_refresh_seconds: int = Field(default=120, ge=15)


@dataclass(slots=True)
class PermissionTrace:
    """Compact summary of a member's admin status for /admin perm."""

    member_id: str
    group_id: str
    member_role: str
    bot_role: str
    is_global_admin: bool
    is_admin: bool
    reason: str


def _bot_cache_key(gateway: Gateway, group_id: str) -> tuple[str, str]:
    bot_id = str(getattr(gateway, "self_id", "") or "default")
    return (bot_id, group_id)


class IdentityModule:
    """Caches bot/member roles across bots & groups and checks admin privileges."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._role_cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._bot_role_cache: dict[tuple[str, str], tuple[str, float]] = {}

    def config(self, group_id: str | None = None) -> IdentityConfig:
        raw = self._store.load_section("identity", group_id=group_id)
        return IdentityConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> IdentityConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(IdentityConfig, key, raw_value)
        validated = IdentityConfig.model_validate(current)
        self._store.save_section(
            "identity",
            validated.model_dump(),
            group_id=group_id,
            defaults=IdentityConfig().model_dump(),
        )
        return validated

    def reset_config(self, group_id: str, key: str | None = None) -> IdentityConfig:
        if key and key not in IdentityConfig.model_fields:
            raise ConfigError(f"Unknown config field: {key}")
        self._store.reset_section("identity", key, group_id=group_id)
        return self.config(group_id)

    @staticmethod
    def _normalize_role(raw_role: object) -> str:
        role = str(raw_role or "member").strip().lower()
        return role if role in {"owner", "admin", "member"} else "member"

    def is_global_admin(self, member_id: str) -> bool:
        """Return True when member_id is registered in the global admins list."""
        return member_id in self.config(None).admins

    async def bot_role(
        self, gateway: Gateway, group_id: str, *, force: bool = False
    ) -> str:
        cfg = self.config(group_id)
        now = time.monotonic()
        cache_key = _bot_cache_key(gateway, group_id)
        cached = self._bot_role_cache.get(cache_key)
        if not force and cached and (now - cached[1]) < cfg.bot_role_refresh_seconds:
            return cached[0]

        try:
            state = await gateway.get_group_bot_state(group_id)
            role = self._normalize_role(state.member_role)
        except Exception:
            role = cached[0] if cached else "member"
        self._bot_role_cache[cache_key] = (role, now)
        return role

    async def member_role(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        force: bool = False,
        ttl_seconds: int | None = None,
    ) -> str:
        cfg = self.config(group_id)
        ttl = ttl_seconds or cfg.role_cache_ttl_seconds
        now = time.monotonic()
        key = (group_id, member_id)
        cached = self._role_cache.get(key)
        if not force and cached and (now - cached[1]) < ttl:
            return cached[0]

        try:
            member = await gateway.get_group_member(group_id, member_id)
            role = self._normalize_role(member.member_role)
        except Exception:
            role = "member"
        self._role_cache[key] = (role, now)
        return role

    def forget_member(self, group_id: str, member_id: str) -> None:
        self._role_cache.pop((group_id, member_id), None)

    def forget_group(self, group_id: str) -> None:
        for key in [k for k in self._bot_role_cache if k[1] == group_id]:
            self._bot_role_cache.pop(key, None)
        for key in [k for k in self._role_cache if k[0] == group_id]:
            self._role_cache.pop(key, None)

    async def is_admin(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Return True if member_id is a global admin or target-group owner/admin."""
        if self.is_global_admin(member_id) or member_id in self.config(group_id).admins:
            return True
        role = await self.member_role(gateway, group_id, member_id, force=force)
        return role in {"owner", "admin"}

    async def permission_trace(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        force: bool = False,
    ) -> PermissionTrace:
        """Return a diagnostic trace of a member's admin status in target group."""
        is_global = self.is_global_admin(member_id)
        in_group_allowlist = member_id in self.config(group_id).admins
        b_role = await self.bot_role(gateway, group_id, force=force)
        m_role = await self.member_role(gateway, group_id, member_id, force=force)
        allowed = is_global or in_group_allowlist or m_role in {"owner", "admin"}
        reason = (
            "global admin"
            if is_global
            else (
                "group allowlist admin"
                if in_group_allowlist
                else (f"group {m_role}" if allowed else "regular member")
            )
        )
        return PermissionTrace(
            member_id=member_id,
            group_id=group_id,
            member_role=m_role,
            bot_role=b_role,
            is_global_admin=is_global,
            is_admin=allowed,
            reason=reason,
        )

    def clear(self) -> None:
        self._role_cache.clear()
        self._bot_role_cache.clear()


IDENTITY = IdentityModule(CONFIG_STORE)


class GroupAdmin:
    """OpsMesh Permission checker matching global admins and group owners/admins."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "GroupAdmin()"

    async def __call__(self, gateway: Gateway, event: GroupMessageEvent) -> bool:
        return await IDENTITY.is_admin(gateway, event.group_openid, event.get_user_id())


GROUP_ADMIN: Permission = Permission(GroupAdmin())

__all__ = [
    "GROUP_ADMIN",
    "IDENTITY",
    "GroupAdmin",
    "IdentityConfig",
    "IdentityModule",
    "PermissionTrace",
]
