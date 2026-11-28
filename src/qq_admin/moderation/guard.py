"""Role-aware 8-step safeguard chain, permission trace, and duration parsing."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
import time
from typing import Literal, TypeAlias

from qq import Gateway

from qq_admin.config import EscalationStep, QQAdminConfig
from qq_admin.state import AdminState

MuteDuration: TypeAlias = int | float | str | timedelta | datetime

_DURATION_RE = re.compile(r"^(\d+)([smhdSMHD]?)$")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
_MAX_QQ_MUTE_SECONDS = 2_592_000


def parse_mute_duration(duration: MuteDuration) -> int:
    """Normalize seconds, shorthand ('10m', '2h', '1d'), timedelta, or datetime."""
    if isinstance(duration, datetime):
        now = datetime.now(UTC)
        target = duration if duration.tzinfo else duration.replace(tzinfo=UTC)
        seconds = int((target - now).total_seconds())
    elif isinstance(duration, timedelta):
        seconds = int(duration.total_seconds())
    elif isinstance(duration, (int, float)):
        seconds = int(duration)
    else:
        match = _DURATION_RE.fullmatch(duration.strip())
        if not match:
            raise ValueError(
                f"Invalid mute duration {duration!r}; expected e.g. 600, '10m', '1h'."
            )
        seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]

    if seconds <= 0 or seconds > _MAX_QQ_MUTE_SECONDS:
        raise ValueError(
            f"Mute duration must be between 1 and {_MAX_QQ_MUTE_SECONDS} seconds."
        )
    return seconds


def format_duration_short(seconds: int) -> str:
    """Format seconds into a compact string like '10m' or '2h'."""
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def is_group_enabled(
    config: QQAdminConfig, state: AdminState, group_openid: str
) -> bool:
    """Return True if automatic moderation is enabled for group_openid."""
    if not config.enabled or not group_openid:
        return False
    if group_openid in state.disabled_groups:
        return False
    whitelist = config.auto_moderate.enabled_groups
    return not whitelist or group_openid in whitelist


async def refresh_bot_role(
    gateway: Gateway,
    config: QQAdminConfig,
    state: AdminState,
    group_openid: str,
    *,
    force: bool = False,
) -> str:
    """Fetch and cache the bot's own role ('owner'/'admin'/'member') in a group."""
    now = time.time()
    cached = state.bot_roles.get(group_openid)
    ttl = max(config.auto_moderate.bot_role_refresh_seconds, 30)
    if not force and cached and (now - cached[1]) < ttl:
        return cached[0]
    try:
        bot_state = await gateway.get_group_bot_state(group_openid)
        role = (bot_state.member_role or "member").lower()
        state.bot_roles[group_openid] = (role, now)
        return role
    except Exception:
        fallback = cached[0] if cached else "member"
        state.bot_roles[group_openid] = (fallback, now - ttl + 60)
        return fallback


async def refresh_member_role(
    gateway: Gateway,
    config: QQAdminConfig,
    state: AdminState,
    group_openid: str,
    member_openid: str,
    *,
    force: bool = False,
    throttle_sender: bool = False,
) -> str:
    """Fetch and cache a member's group role ('owner'/'admin'/'member')."""
    now = time.time()
    key = (group_openid, member_openid)
    cached = state.member_roles.get(key)
    ttl = max(config.auto_moderate.role_cache_ttl_seconds, 30)
    if not force and cached and (now - cached[1]) < ttl:
        return cached[0]
    if throttle_sender and not force:
        last_check = state.sender_refreshed_at.get(key, 0.0)
        if now - last_check < config.auto_moderate.sender_role_refresh_seconds:
            return cached[0] if cached else "member"
        state.sender_refreshed_at[key] = now
    try:
        info = await gateway.get_group_member(group_openid, member_openid)
        role = (info.member_role or "member").lower()
        state.member_roles[key] = (role, now)
        return role
    except Exception:
        return cached[0] if cached else "member"


@dataclass(slots=True)
class PermissionTrace:
    """Step-by-step trace rendered by /admin perm for debugging access decisions."""

    group_openid: str
    member_openid: str
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    allowed: bool = False
    reason: str = ""

    def add(self, label: str, passed: bool, detail: str = "") -> None:
        self.steps.append((label, passed, detail))

    def format_text(self) -> str:
        lines = [
            f"PermissionTrace group={self.group_openid} member={self.member_openid}"
        ]
        for idx, (label, passed, detail) in enumerate(self.steps, start=1):
            mark = "OK" if passed else "NO"
            suffix = f" - {detail}" if detail else ""
            lines.append(f"  {idx}. [{mark}] {label}{suffix}")
        verdict = "ALLOW" if self.allowed else "DENY"
        tail = f" ({self.reason})" if self.reason else ""
        lines.append(f"  Verdict: {verdict}{tail}")
        return "\n".join(lines)


async def evaluate_command_permission(
    gateway: Gateway,
    config: QQAdminConfig,
    state: AdminState,
    group_openid: str,
    operator_openid: str,
    *,
    minimum_role: Literal["member", "admin", "owner", "global"] = "admin",
    command_name: str = "",
    force_refresh: bool = False,
) -> tuple[bool, PermissionTrace]:
    """Evaluate union permission chain: global admin > group owner > group admin."""
    trace = PermissionTrace(group_openid=group_openid, member_openid=operator_openid)
    in_global = operator_openid in config.admin.admins
    trace.add("global_admin", in_global, f"in admin.admins={in_global}")

    role = await refresh_member_role(
        gateway,
        config,
        state,
        group_openid,
        operator_openid,
        force=force_refresh,
    )
    trace.add("member_role", role in ("owner", "admin"), f"role={role}")

    if in_global:
        trace.allowed = True
        trace.reason = "global admin"
        return True, trace

    if minimum_role == "member":
        trace.allowed = True
        trace.reason = "member level allowed"
        return True, trace

    if role == "owner" and config.admin.allow_group_owner:
        allowed_cmds = config.admin.owner_allowed_commands
        cmd_ok = not allowed_cmds or not command_name or command_name in allowed_cmds
        trace.add("owner_whitelist", cmd_ok, f"command={command_name or '*'}")
        if cmd_ok:
            trace.allowed = True
            trace.reason = "group owner"
            return True, trace

    if minimum_role == "admin" and role == "admin":
        trace.allowed = True
        trace.reason = "group admin"
        return True, trace

    trace.allowed = False
    trace.reason = f"requires {minimum_role}, got {role}"
    return False, trace


@dataclass(frozen=True, slots=True)
class GuardDecision:
    """Outcome of the role-aware 8-step safeguard evaluation."""

    allowed: bool
    reason: str = ""
    step: str = ""
    adjusted_duration: int | None = None
    escalated_action: Literal["mute", "kick"] | None = None
    escalate_blacklist: bool = False


def match_escalation_step(
    config: QQAdminConfig,
    state: AdminState,
    group_openid: str,
    target_openid: str,
) -> EscalationStep | None:
    """Return the highest matching escalation step for target_openid, if any."""
    if not config.escalation.enabled or not config.escalation.steps:
        return None
    matched: EscalationStep | None = None
    for step in config.escalation.steps:
        ops = state.count_recent_ops(group_openid, target_openid, step.within_hours)
        if ops >= step.count:
            matched = step
    return matched


async def check_action_guard(
    gateway: Gateway,
    config: QQAdminConfig,
    state: AdminState,
    *,
    group_openid: str,
    target_openid: str,
    action: Literal["warn", "mute", "kick", "ban", "recall"],
    duration_seconds: int | None = None,
    require_member_check: bool = False,
) -> GuardDecision:
    """Run role-aware 8-step safeguard checks before executing a moderation action."""
    bot_role = await refresh_bot_role(gateway, config, state, group_openid)
    if bot_role not in ("owner", "admin"):
        return GuardDecision(
            allowed=False,
            reason="Bot is neither group owner nor admin.",
            step="bot_role",
        )

    if bot_role == "owner":
        return GuardDecision(allowed=True, adjusted_duration=duration_seconds)

    sf = config.safeguard
    if target_openid in sf.protected_users:
        return GuardDecision(
            allowed=False,
            reason="Target is in global protected_users.",
            step="protected_users",
        )

    if target_openid in state.exempt_users.get(group_openid, set()):
        return GuardDecision(
            allowed=False,
            reason="Target is in group exempt_users.",
            step="exempt_users",
        )

    if target_openid in config.admin.admins:
        return GuardDecision(
            allowed=False,
            reason="Target is a global bot admin.",
            step="global_admins",
        )

    if sf.auto_exempt_admins:
        target_role = await refresh_member_role(
            gateway, config, state, group_openid, target_openid
        )
        if _ROLE_RANK.get(target_role, 0) >= _ROLE_RANK["admin"]:
            return GuardDecision(
                allowed=False,
                reason=f"Target is group {target_role} and auto-exempted.",
                step="auto_exempt_admins",
            )

    now = time.time()
    if action == "mute":
        if sf.mute_cooldown > 0:
            last_mute = state.last_mute_at.get((group_openid, target_openid), 0.0)
            if last_mute > 0 and (now - last_mute) < sf.mute_cooldown:
                remain = int(sf.mute_cooldown - (now - last_mute))
                return GuardDecision(
                    allowed=False,
                    reason=f"Mute cooldown active ({remain}s remaining).",
                    step="mute_cooldown",
                )
        if state.get_daily_count(group_openid, "mute") >= sf.daily_mute_limit:
            return GuardDecision(
                allowed=False,
                reason=f"Daily mute limit reached ({sf.daily_mute_limit}).",
                step="daily_mute_limit",
            )

    if action == "kick":
        if require_member_check and sf.kick_require_member_check:
            if not state.was_member_checked_recently(group_openid, target_openid):
                return GuardDecision(
                    allowed=False,
                    reason="Call group_get_member to verify target before kicking.",
                    step="kick_member_check",
                )
        if state.get_daily_count(group_openid, "kick") >= sf.daily_kick_limit:
            return GuardDecision(
                allowed=False,
                reason=f"Daily kick limit reached ({sf.daily_kick_limit}).",
                step="daily_kick_limit",
            )

    adjusted = duration_seconds
    escalated_action: Literal["mute", "kick"] | None = None
    escalate_blacklist = False
    esc = match_escalation_step(config, state, group_openid, target_openid)
    if esc is not None and action in ("mute", "kick"):
        escalated_action = esc.action
        escalate_blacklist = esc.add_to_blacklist
        if action == "mute" and esc.action == "mute":
            adjusted = (
                min(adjusted, esc.mute_seconds)
                if adjusted is not None
                else esc.mute_seconds
            )

    if action == "mute" and adjusted is not None:
        adjusted = min(adjusted, sf.max_mute_duration)

    return GuardDecision(
        allowed=True,
        adjusted_duration=adjusted,
        escalated_action=escalated_action,
        escalate_blacklist=escalate_blacklist,
    )


__all__ = [
    "GuardDecision",
    "MuteDuration",
    "PermissionTrace",
    "check_action_guard",
    "evaluate_command_permission",
    "format_duration_short",
    "is_group_enabled",
    "match_escalation_step",
    "parse_mute_duration",
    "refresh_bot_role",
    "refresh_member_role",
]
