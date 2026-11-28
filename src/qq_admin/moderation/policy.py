"""Role-aware 8-step safeguard policy and command authorization trace."""

from dataclasses import dataclass, field
import time
from typing import Literal

from qq import Gateway

from qq_admin.config import AdminConfig, EscalationRule
from qq_admin.state import GroupStateStore

_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
MinimumRole = Literal["member", "admin", "owner", "global"]
WriteAction = Literal["warn", "mute", "kick", "ban", "recall"]


@dataclass(slots=True)
class PermissionTrace:
    """Step-by-step decision record rendered by /admin perm."""

    group_id: str
    member_id: str
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    allowed: bool = False
    reason: str = ""

    def record(self, step: str, passed: bool, detail: str = "") -> None:
        self.steps.append((step, passed, detail))

    def format_text(self) -> str:
        lines = [f"PermissionTrace group={self.group_id} member={self.member_id}"]
        for idx, (step, passed, detail) in enumerate(self.steps, start=1):
            mark = "OK" if passed else "NO"
            suffix = f" - {detail}" if detail else ""
            lines.append(f"  {idx}. [{mark}] {step}{suffix}")
        verdict = "ALLOW" if self.allowed else "DENY"
        tail = f" ({self.reason})" if self.reason else ""
        lines.append(f"  Verdict: {verdict}{tail}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    """Result of the role-aware 8-step safeguard check."""

    allowed: bool
    reason: str = ""
    step: str = ""
    adjusted_duration: int | None = None
    escalated_action: Literal["mute", "kick"] | None = None
    escalate_blacklist: bool = False


class SafeguardPolicy:
    """Evaluates operator authorization, role hierarchy, quotas, and ladders."""

    def __init__(self, config: AdminConfig, state: GroupStateStore) -> None:
        self.config = config
        self.state = state

    def is_group_active(self, group_id: str) -> bool:
        if not self.config.plugin.enabled or not group_id:
            return False
        if group_id in self.state.paused_groups:
            return False
        allowlist = self.config.moderation.enabled_groups
        return not allowlist or group_id in allowlist

    async def bot_role(
        self, gateway: Gateway, group_id: str, *, force: bool = False
    ) -> str:
        now = time.time()
        cached = self.state.bot_roles.get(group_id)
        ttl = max(self.config.identity.bot_role_refresh_seconds, 30)
        if not force and cached and (now - cached[1]) < ttl:
            return cached[0]
        try:
            bot_state = await gateway.get_group_bot_state(group_id)
            role = (bot_state.member_role or "member").lower()
            self.state.bot_roles[group_id] = (role, now)
            return role
        except Exception:
            fallback = cached[0] if cached else "member"
            self.state.bot_roles[group_id] = (fallback, now - ttl + 60)
            return fallback

    async def member_role(
        self,
        gateway: Gateway,
        group_id: str,
        member_id: str,
        *,
        force: bool = False,
        throttle: bool = False,
    ) -> str:
        now = time.time()
        key = (group_id, member_id)
        cached = self.state.member_roles.get(key)
        ttl = max(self.config.identity.role_cache_ttl_seconds, 30)
        if not force and cached and (now - cached[1]) < ttl:
            return cached[0]
        if throttle and not force:
            last = self.state.sender_checked_at.get(key, 0.0)
            if now - last < self.config.identity.sender_role_refresh_seconds:
                return cached[0] if cached else "member"
            self.state.sender_checked_at[key] = now
        try:
            info = await gateway.get_group_member(group_id, member_id)
            role = (info.member_role or "member").lower()
            self.state.member_roles[key] = (role, now)
            return role
        except Exception:
            return cached[0] if cached else "member"

    async def authorize(
        self,
        gateway: Gateway,
        group_id: str,
        operator_id: str,
        *,
        minimum_role: MinimumRole = "admin",
        command: str = "",
        force: bool = False,
    ) -> tuple[bool, PermissionTrace]:
        """Verify union authorization: global admin > group owner > group admin."""
        trace = PermissionTrace(group_id=group_id, member_id=operator_id)
        is_global = operator_id in self.config.admin.admins
        trace.record("global_admin", is_global, f"in admin.admins={is_global}")

        role = await self.member_role(gateway, group_id, operator_id, force=force)
        trace.record("member_role", role in ("owner", "admin"), f"role={role}")

        if is_global:
            trace.allowed, trace.reason = True, "global admin"
            return True, trace

        if minimum_role == "member":
            trace.allowed, trace.reason = True, "member allowed"
            return True, trace

        if role == "owner" and self.config.admin.allow_group_owner:
            allow_cmds = self.config.admin.owner_allowed_commands
            ok = not allow_cmds or not command or command in allow_cmds
            trace.record("owner_allowlist", ok, f"command={command or '*'}")
            if ok:
                trace.allowed, trace.reason = True, "group owner"
                return True, trace

        if minimum_role == "admin" and role == "admin":
            trace.allowed, trace.reason = True, "group admin"
            return True, trace

        trace.allowed = False
        trace.reason = f"requires {minimum_role}, got {role}"
        return False, trace

    def matched_escalation(
        self, group_id: str, target_id: str
    ) -> EscalationRule | None:
        esc = self.config.escalation
        if not esc.enabled or not esc.steps:
            return None
        matched: EscalationRule | None = None
        for rule in esc.steps:
            if (
                self.state.count_violations(group_id, target_id, rule.within_hours)
                >= rule.count
            ):
                matched = rule
        return matched

    async def verify_action(
        self,
        gateway: Gateway,
        group_id: str,
        target_id: str,
        action: WriteAction,
        *,
        duration: int | None = None,
        require_confirm: bool = False,
    ) -> PolicyVerdict:
        """Run the role-aware 8-step safeguard chain before executing an action."""
        bot_role = await self.bot_role(gateway, group_id)
        if bot_role not in ("owner", "admin"):
            return PolicyVerdict(
                allowed=False,
                reason="Bot is neither group owner nor admin.",
                step="bot_role",
            )
        if bot_role == "owner":
            return PolicyVerdict(allowed=True, adjusted_duration=duration)

        target_block = await self._check_target_protection(gateway, group_id, target_id)
        if target_block is not None:
            return target_block

        quota_block = self._check_quotas_and_confirm(
            group_id, target_id, action, require_confirm=require_confirm
        )
        if quota_block is not None:
            return quota_block

        return self._apply_escalation_caps(group_id, target_id, action, duration)

    async def _check_target_protection(
        self, gateway: Gateway, group_id: str, target_id: str
    ) -> PolicyVerdict | None:
        sf = self.config.safeguard
        if target_id in sf.protected_users:
            return PolicyVerdict(
                allowed=False,
                reason="Target is in global protected_users.",
                step="protected_users",
            )
        if target_id in self.state.exempt_members.get(group_id, set()):
            return PolicyVerdict(
                allowed=False,
                reason="Target is in group exempt_users.",
                step="exempt_users",
            )
        if target_id in self.config.admin.admins:
            return PolicyVerdict(
                allowed=False,
                reason="Target is a global bot admin.",
                step="global_admins",
            )
        if sf.auto_exempt_admins:
            role = await self.member_role(gateway, group_id, target_id)
            if _ROLE_RANK.get(role, 0) >= _ROLE_RANK["admin"]:
                return PolicyVerdict(
                    allowed=False,
                    reason=f"Target is group {role} and auto-exempted.",
                    step="auto_exempt_admins",
                )
        return None

    def _check_quotas_and_confirm(
        self,
        group_id: str,
        target_id: str,
        action: WriteAction,
        *,
        require_confirm: bool,
    ) -> PolicyVerdict | None:
        sf = self.config.safeguard
        if action == "mute":
            remain = self.state.cooldown_remaining(
                group_id, target_id, sf.mute_cooldown
            )
            if remain > 0:
                return PolicyVerdict(
                    allowed=False,
                    reason=f"Mute cooldown active ({remain}s remaining).",
                    step="mute_cooldown",
                )
            if self.state.daily_count(group_id, "mute") >= sf.daily_mute_limit:
                return PolicyVerdict(
                    allowed=False,
                    reason=f"Daily mute limit reached ({sf.daily_mute_limit}).",
                    step="daily_mute_limit",
                )
        if action == "kick":
            if (
                require_confirm
                and sf.kick_require_confirm
                and not self.state.is_member_verified(group_id, target_id)
            ):
                return PolicyVerdict(
                    allowed=False,
                    reason="Call get_member to verify target before kicking.",
                    step="kick_confirm",
                )
            if self.state.daily_count(group_id, "kick") >= sf.daily_kick_limit:
                return PolicyVerdict(
                    allowed=False,
                    reason=f"Daily kick limit reached ({sf.daily_kick_limit}).",
                    step="daily_kick_limit",
                )
        return None

    def _apply_escalation_caps(
        self,
        group_id: str,
        target_id: str,
        action: WriteAction,
        duration: int | None,
    ) -> PolicyVerdict:
        adjusted = duration
        escalated_action: Literal["mute", "kick"] | None = None
        escalate_blacklist = False

        rule = self.matched_escalation(group_id, target_id)
        if rule is not None and action in ("mute", "kick"):
            escalated_action = rule.action
            escalate_blacklist = rule.blacklist
            if action == "mute" and rule.action == "mute":
                adjusted = (
                    min(adjusted, rule.mute_seconds)
                    if adjusted is not None
                    else rule.mute_seconds
                )

        if action == "mute" and adjusted is not None:
            adjusted = min(adjusted, self.config.safeguard.max_mute_duration)

        return PolicyVerdict(
            allowed=True,
            adjusted_duration=adjusted,
            escalated_action=escalated_action,
            escalate_blacklist=escalate_blacklist,
        )


__all__ = [
    "MinimumRole",
    "PermissionTrace",
    "PolicyVerdict",
    "SafeguardPolicy",
    "WriteAction",
]
