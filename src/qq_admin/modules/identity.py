"""Identity and command authorization module with self-owned IdentityConfig."""

from dataclasses import dataclass, field
import time
from typing import Literal

from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.config import ConfigStore, parse_field_value

MinimumRole = Literal["global_admin", "owner", "admin", "member"]


class IdentityConfig(BaseModel):
    """Role lookup TTLs and human administrator authorization rules."""

    admins: list[str] = Field(
        default_factory=list, description="Global admin member_openid allowlist."
    )
    allow_group_owner: bool = Field(
        default=True, description="Allow group owners to run /admin commands."
    )
    owner_allowed_commands: list[str] = Field(
        default_factory=list,
        description="Optional subcommand allowlist for group owners.",
    )
    deny_response: Literal["silent", "reply"] = Field(
        default="silent",
        description="Behavior when an unauthorized user runs a command.",
    )
    role_cache_ttl_seconds: int = Field(default=600, ge=30)
    bot_role_refresh_seconds: int = Field(default=300, ge=30)
    sender_role_refresh_seconds: int = Field(default=120, ge=15)


@dataclass(slots=True)
class PermissionTrace:
    """Diagnostic trace explaining why a user was granted or denied access."""

    member_id: str
    group_id: str
    member_role: str
    bot_role: str
    is_global_admin: bool
    allowed: bool
    reason: str
    steps: list[str] = field(default_factory=list)


class IdentityModule:
    """Manages group member/bot role caching and command authorization."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._role_cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._bot_role_cache: dict[str, tuple[str, float]] = {}

    def config(self, group_id: str | None = None) -> IdentityConfig:
        raw = self._store.load_section("identity", group_id=group_id)
        return IdentityConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> IdentityConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(IdentityConfig, key, raw_value)
        validated = IdentityConfig.model_validate(current)
        self._store.save_section("identity", validated.model_dump(), group_id=group_id)
        return validated

    @staticmethod
    def _normalize_role(raw_role: object) -> str:
        role = str(raw_role or "member").strip().lower()
        if role in {"owner", "admin", "member"}:
            return role
        return "member"

    async def bot_role(
        self, gateway: Gateway, group_id: str, *, force: bool = False
    ) -> str:
        cfg = self.config(group_id)
        now = time.monotonic()
        cached = self._bot_role_cache.get(group_id)
        if not force and cached and (now - cached[1]) < cfg.bot_role_refresh_seconds:
            return cached[0]

        try:
            state = await gateway.get_group_bot_state(group_id)
            role = self._normalize_role(state.member_role)
        except Exception:
            role = cached[0] if cached else "member"
        self._bot_role_cache[group_id] = (role, now)
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
        self._bot_role_cache.pop(group_id, None)
        stale = [k for k in self._role_cache if k[0] == group_id]
        for key in stale:
            self._role_cache.pop(key, None)

    async def authorize(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        minimum_role: MinimumRole = "admin",
        command: str = "",
        force_refresh: bool = False,
    ) -> tuple[bool, PermissionTrace]:
        cfg = self.config(group_id)
        steps: list[str] = []
        is_global_admin = member_id in cfg.admins
        b_role = await self.bot_role(gateway, group_id, force=force_refresh)
        m_role = await self.member_role(
            gateway, group_id, member_id, force=force_refresh
        )
        steps.append(f"member_role={m_role}, bot_role={b_role}")

        if is_global_admin:
            steps.append("matched identity.admins allowlist")
            return True, PermissionTrace(
                member_id=member_id,
                group_id=group_id,
                member_role=m_role,
                bot_role=b_role,
                is_global_admin=True,
                allowed=True,
                reason="global admin allowlist",
                steps=steps,
            )

        if minimum_role == "member":
            steps.append("member-level command allowed")
            return True, PermissionTrace(
                member_id=member_id,
                group_id=group_id,
                member_role=m_role,
                bot_role=b_role,
                is_global_admin=False,
                allowed=True,
                reason="member access",
                steps=steps,
            )

        if minimum_role == "global_admin":
            if m_role == "owner" and cfg.allow_group_owner:
                if (
                    not cfg.owner_allowed_commands
                    or not command
                    or command in cfg.owner_allowed_commands
                ):
                    steps.append("group owner authorized via allow_group_owner")
                    return True, PermissionTrace(
                        member_id=member_id,
                        group_id=group_id,
                        member_role=m_role,
                        bot_role=b_role,
                        is_global_admin=False,
                        allowed=True,
                        reason="group owner authorized",
                        steps=steps,
                    )
                steps.append(f"command '{command}' not in owner_allowed_commands")
            else:
                steps.append("requires global admin or authorized group owner")
            return False, PermissionTrace(
                member_id=member_id,
                group_id=group_id,
                member_role=m_role,
                bot_role=b_role,
                is_global_admin=False,
                allowed=False,
                reason="admin permission required",
                steps=steps,
            )

        if minimum_role == "owner":
            allowed = m_role == "owner"
            steps.append("owner check passed" if allowed else "requires group owner")
            return allowed, PermissionTrace(
                member_id=member_id,
                group_id=group_id,
                member_role=m_role,
                bot_role=b_role,
                is_global_admin=False,
                allowed=allowed,
                reason="group owner" if allowed else "requires group owner",
                steps=steps,
            )

        allowed = m_role in {"owner", "admin"}
        steps.append(
            "group admin/owner check passed"
            if allowed
            else "requires group admin or owner"
        )
        return allowed, PermissionTrace(
            member_id=member_id,
            group_id=group_id,
            member_role=m_role,
            bot_role=b_role,
            is_global_admin=False,
            allowed=allowed,
            reason="group admin/owner" if allowed else "requires group admin",
            steps=steps,
        )


__all__ = [
    "IdentityConfig",
    "IdentityModule",
    "MinimumRole",
    "PermissionTrace",
]
