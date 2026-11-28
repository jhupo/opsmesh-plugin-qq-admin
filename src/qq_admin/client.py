"""High-cohesion official QQ Group v2 administration client classes."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
import re
from typing import Literal, TypeAlias

from opsmesh.adapters import Event
from qq import (
    BatchRemoveMembersReturn,
    BlacklistUser,
    Gateway,
    GlobalMuteRule,
    GroupBotStateReturn,
    GroupInfoReturn,
    GroupMemberBlacklistReturn,
    GroupMemberInfo,
    GroupMembersReturn,
    GroupMessageEvent,
    GroupNoticeEvent,
    GroupRestrictChatSettingReturn,
    InteractionCreateEvent,
    JoinRequest,
    JoinRequestListReturn,
    MemberBlacklistOpReturn,
    MemberMuteState,
    PostGroupMembersReturn,
    SetMemberMuteState,
)

from .exception import BotNotAdminError, GroupTargetRequiredError, HierarchyError

MuteDuration: TypeAlias = int | float | str | timedelta | datetime

_DURATION_RE = re.compile(r"^(\d+)([smhdSMHD]?)$")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}


def parse_mute_duration(duration: MuteDuration) -> timedelta | datetime:
    """Normalize seconds, shorthand ('10m', '2h', '1d'), timedelta, or datetime."""
    if isinstance(duration, datetime):
        return duration
    if isinstance(duration, timedelta):
        if duration.total_seconds() <= 0:
            raise ValueError("Mute duration must be positive.")
        return duration
    if isinstance(duration, (int, float)):
        if duration <= 0:
            raise ValueError("Mute duration seconds must be positive.")
        return timedelta(seconds=float(duration))

    match = _DURATION_RE.fullmatch(duration.strip())
    if not match:
        raise ValueError(
            f"Invalid mute duration {duration!r}; "
            "expected e.g. 600, '30s', '10m', '2h', '1d'."
        )
    seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds <= 0:
        raise ValueError("Mute duration seconds must be positive.")
    return timedelta(seconds=seconds)


def can_manage_member(operator_role: str, target_role: str) -> bool:
    """Return True if operator_role strictly outranks target_role in QQ group."""
    op_rank = _ROLE_RANK.get(operator_role.lower(), 0)
    tgt_rank = _ROLE_RANK.get(target_role.lower(), 0)
    return op_rank > tgt_rank and tgt_rank < _ROLE_RANK["owner"]


def ensure_can_manage(operator_role: str, target_role: str) -> None:
    """Raise HierarchyError if operator_role is not allowed to manage target_role."""
    if not can_manage_member(operator_role, target_role):
        raise HierarchyError(
            f"Role {operator_role!r} cannot manage member with role {target_role!r}."
        )


def extract_group_openid(event: Event) -> str:
    """Extract group_openid from any QQ group message, notice, or interaction event."""
    if isinstance(event, (GroupMessageEvent, GroupNoticeEvent)) and event.group_openid:
        return event.group_openid
    if isinstance(event, InteractionCreateEvent) and event.group_openid:
        return event.group_openid
    raise GroupTargetRequiredError(
        f"Event {type(event).__name__} does not carry a group_openid."
    )


class QQGroupAdmin:
    """Stateless client encapsulating Official QQ Bot v2 Group Admin capabilities."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway: Gateway = gateway

    def group(self, group_openid: str) -> "QQGroupScope":
        """Bind a specific group_openid and return a single-group QQGroupScope."""
        return QQGroupScope(self, group_openid)

    @classmethod
    def from_event(cls, gateway: Gateway, event: Event) -> "QQGroupScope":
        """Create a group-scoped QQGroupScope directly from an inbound group event."""
        return cls(gateway).group(extract_group_openid(event))

    # --- 1. Group Overview & Bot State ---

    async def get_info(self, group_openid: str) -> GroupInfoReturn:
        return await self.gateway.get_group_info(group_openid)

    async def get_bot_state(self, group_openid: str) -> GroupBotStateReturn:
        return await self.gateway.get_group_bot_state(group_openid)

    async def is_bot_admin(self, group_openid: str) -> bool:
        state = await self.get_bot_state(group_openid)
        return state.member_role.lower() in {"admin", "owner"}

    async def ensure_bot_admin(self, group_openid: str) -> GroupBotStateReturn:
        state = await self.get_bot_state(group_openid)
        if state.member_role.lower() not in {"admin", "owner"}:
            raise BotNotAdminError(
                f"Bot role in group {group_openid} is {state.member_role!r}; "
                "admin or owner required."
            )
        return state

    # --- 2. Group Member Queries & Auto-Pagination ---

    async def get_member(
        self, group_openid: str, member_openid: str
    ) -> GroupMemberInfo:
        return await self.gateway.get_group_member(group_openid, member_openid)

    async def list_members(
        self,
        group_openid: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> GroupMembersReturn:
        return await self.gateway.get_group_members(
            group_openid, cursor=cursor, limit=limit
        )

    async def list_members_by_index(
        self,
        group_openid: str,
        *,
        start_index: int | None = None,
        limit: int | None = None,
    ) -> PostGroupMembersReturn:
        return await self.gateway.post_group_members(
            group_openid, limit=limit, start_index=start_index
        )

    async def iter_members(
        self, group_openid: str, *, limit: int | None = None
    ) -> AsyncIterator[GroupMemberInfo]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.list_members(group_openid, cursor=cursor, limit=limit)
            for member in page.members:
                yield member
            if not page.next_cursor or page.next_cursor in seen_cursors:
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def get_all_members(
        self, group_openid: str, *, limit: int | None = None
    ) -> list[GroupMemberInfo]:
        return [m async for m in self.iter_members(group_openid, limit=limit)]

    # --- 3. Mute Management ---

    async def get_mute_setting(
        self, group_openid: str
    ) -> GroupRestrictChatSettingReturn:
        return await self.gateway.get_group_mute_setting(group_openid)

    async def get_global_mute_rule(self, group_openid: str) -> GlobalMuteRule:
        setting = await self.get_mute_setting(group_openid)
        return setting.global_rule

    async def list_muted_members(self, group_openid: str) -> list[MemberMuteState]:
        setting = await self.get_mute_setting(group_openid)
        return setting.members

    async def mute(
        self,
        group_openid: str,
        member_openid: str,
        duration: MuteDuration = 600,
        *,
        op: Literal["add", "update"] = "add",
    ) -> None:
        await self.mute_many(group_openid, [member_openid], duration, op=op)

    async def mute_many(
        self,
        group_openid: str,
        member_openids: Sequence[str],
        duration: MuteDuration = 600,
        *,
        op: Literal["add", "update"] = "add",
    ) -> None:
        if not member_openids:
            return
        expire = parse_mute_duration(duration)
        items = [
            SetMemberMuteState(
                member_openid=mid,
                op=op,
                mute_expire_at=expire,
            )
            for mid in member_openids
        ]
        await self.gateway.set_group_members_mute(group_openid, items)

    async def unmute(self, group_openid: str, member_openid: str) -> None:
        await self.unmute_many(group_openid, [member_openid])

    async def unmute_many(
        self, group_openid: str, member_openids: Sequence[str]
    ) -> None:
        if not member_openids:
            return
        items = [
            SetMemberMuteState(member_openid=mid, op="del") for mid in member_openids
        ]
        await self.gateway.set_group_members_mute(group_openid, items)

    # --- 4. Kick / Remove Members ---

    async def kick(
        self,
        group_openid: str,
        member_openid: str,
        *,
        add_to_blacklist: bool = False,
    ) -> BatchRemoveMembersReturn:
        return await self.kick_many(
            group_openid, [member_openid], add_to_blacklist=add_to_blacklist
        )

    async def kick_many(
        self,
        group_openid: str,
        member_openids: Sequence[str],
        *,
        add_to_blacklist: bool = False,
    ) -> BatchRemoveMembersReturn:
        return await self.gateway.batch_remove_group_members(
            group_openid,
            list(member_openids),
            add_to_member_blacklist=add_to_blacklist,
        )

    # --- 5. Group Blacklist Management & Auto-Pagination ---

    async def list_blacklist(
        self,
        group_openid: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> GroupMemberBlacklistReturn:
        return await self.gateway.get_group_member_blacklist(
            group_openid, cursor=cursor, limit=limit
        )

    async def iter_blacklist(
        self, group_openid: str, *, limit: int | None = None
    ) -> AsyncIterator[BlacklistUser]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.list_blacklist(group_openid, cursor=cursor, limit=limit)
            for user in page.users:
                yield user
            if not page.next_cursor or page.next_cursor in seen_cursors:
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def get_all_blacklist(
        self, group_openid: str, *, limit: int | None = None
    ) -> list[BlacklistUser]:
        return [u async for u in self.iter_blacklist(group_openid, limit=limit)]

    async def ban(
        self, group_openid: str, member_openid: str
    ) -> MemberBlacklistOpReturn:
        return await self.ban_many(group_openid, [member_openid])

    async def ban_many(
        self, group_openid: str, member_openids: Sequence[str]
    ) -> MemberBlacklistOpReturn:
        return await self.gateway.post_group_member_blacklist(
            group_openid, op="add", member_openids=list(member_openids)
        )

    async def unban(
        self, group_openid: str, member_openid: str
    ) -> MemberBlacklistOpReturn:
        return await self.unban_many(group_openid, [member_openid])

    async def unban_many(
        self, group_openid: str, member_openids: Sequence[str]
    ) -> MemberBlacklistOpReturn:
        return await self.gateway.post_group_member_blacklist(
            group_openid, op="del", member_openids=list(member_openids)
        )

    # --- 6. Join Requests & Message Recall ---

    async def list_join_requests(
        self,
        group_openid: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> JoinRequestListReturn:
        return await self.gateway.get_group_join_request_list(
            group_openid, cursor=cursor, limit=limit
        )

    async def iter_join_requests(
        self, group_openid: str, *, limit: int | None = None
    ) -> AsyncIterator[JoinRequest]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.list_join_requests(
                group_openid, cursor=cursor, limit=limit
            )
            for req in page.list:
                yield req
            if not page.next_cursor or page.next_cursor in seen_cursors:
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def get_all_join_requests(
        self, group_openid: str, *, limit: int | None = None
    ) -> list[JoinRequest]:
        return [r async for r in self.iter_join_requests(group_openid, limit=limit)]

    async def approve_join(
        self,
        group_openid: str,
        member_openid: str,
        *,
        join_request_id: str | None = None,
    ) -> None:
        await self.gateway.approval_join_request(
            group_openid,
            member_openid,
            op="approve",
            join_request_id=join_request_id,
        )

    async def reject_join(
        self,
        group_openid: str,
        member_openid: str,
        *,
        join_request_id: str | None = None,
        reason: str | None = None,
        add_to_blacklist: bool = False,
    ) -> None:
        await self.gateway.approval_join_request(
            group_openid,
            member_openid,
            op="decline",
            join_request_id=join_request_id,
            reject_reason=reason,
            add_to_member_blacklist=add_to_blacklist,
        )

    async def recall(self, group_openid: str, message_id: str) -> None:
        await self.gateway.delete_group_message(group_openid, message_id)


class QQGroupScope:
    """Single-group bound view over QQGroupAdmin (omits group_openid on every call)."""

    def __init__(self, admin: QQGroupAdmin, group_openid: str) -> None:
        self.admin: QQGroupAdmin = admin
        self.group_openid: str = group_openid

    @property
    def gateway(self) -> Gateway:
        return self.admin.gateway

    # --- 1. Group Overview & Bot State ---

    async def get_info(self) -> GroupInfoReturn:
        return await self.admin.get_info(self.group_openid)

    async def get_bot_state(self) -> GroupBotStateReturn:
        return await self.admin.get_bot_state(self.group_openid)

    async def is_bot_admin(self) -> bool:
        return await self.admin.is_bot_admin(self.group_openid)

    async def ensure_bot_admin(self) -> GroupBotStateReturn:
        return await self.admin.ensure_bot_admin(self.group_openid)

    # --- 2. Group Members ---

    async def get_member(self, member_openid: str) -> GroupMemberInfo:
        return await self.admin.get_member(self.group_openid, member_openid)

    async def list_members(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> GroupMembersReturn:
        return await self.admin.list_members(
            self.group_openid, cursor=cursor, limit=limit
        )

    async def list_members_by_index(
        self, *, start_index: int | None = None, limit: int | None = None
    ) -> PostGroupMembersReturn:
        return await self.admin.list_members_by_index(
            self.group_openid, start_index=start_index, limit=limit
        )

    def iter_members(
        self, *, limit: int | None = None
    ) -> AsyncIterator[GroupMemberInfo]:
        return self.admin.iter_members(self.group_openid, limit=limit)

    async def get_all_members(
        self, *, limit: int | None = None
    ) -> list[GroupMemberInfo]:
        return await self.admin.get_all_members(self.group_openid, limit=limit)

    # --- 3. Mute Management ---

    async def get_mute_setting(self) -> GroupRestrictChatSettingReturn:
        return await self.admin.get_mute_setting(self.group_openid)

    async def get_global_mute_rule(self) -> GlobalMuteRule:
        return await self.admin.get_global_mute_rule(self.group_openid)

    async def list_muted_members(self) -> list[MemberMuteState]:
        return await self.admin.list_muted_members(self.group_openid)

    async def mute(
        self,
        member_openid: str,
        duration: MuteDuration = 600,
        *,
        op: Literal["add", "update"] = "add",
    ) -> None:
        await self.admin.mute(self.group_openid, member_openid, duration, op=op)

    async def mute_many(
        self,
        member_openids: Sequence[str],
        duration: MuteDuration = 600,
        *,
        op: Literal["add", "update"] = "add",
    ) -> None:
        await self.admin.mute_many(self.group_openid, member_openids, duration, op=op)

    async def unmute(self, member_openid: str) -> None:
        await self.admin.unmute(self.group_openid, member_openid)

    async def unmute_many(self, member_openids: Sequence[str]) -> None:
        await self.admin.unmute_many(self.group_openid, member_openids)

    # --- 4. Kick / Remove Members ---

    async def kick(
        self, member_openid: str, *, add_to_blacklist: bool = False
    ) -> BatchRemoveMembersReturn:
        return await self.admin.kick(
            self.group_openid, member_openid, add_to_blacklist=add_to_blacklist
        )

    async def kick_many(
        self, member_openids: Sequence[str], *, add_to_blacklist: bool = False
    ) -> BatchRemoveMembersReturn:
        return await self.admin.kick_many(
            self.group_openid, member_openids, add_to_blacklist=add_to_blacklist
        )

    # --- 5. Blacklist Management ---

    async def list_blacklist(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> GroupMemberBlacklistReturn:
        return await self.admin.list_blacklist(
            self.group_openid, cursor=cursor, limit=limit
        )

    def iter_blacklist(
        self, *, limit: int | None = None
    ) -> AsyncIterator[BlacklistUser]:
        return self.admin.iter_blacklist(self.group_openid, limit=limit)

    async def get_all_blacklist(
        self, *, limit: int | None = None
    ) -> list[BlacklistUser]:
        return await self.admin.get_all_blacklist(self.group_openid, limit=limit)

    async def ban(self, member_openid: str) -> MemberBlacklistOpReturn:
        return await self.admin.ban(self.group_openid, member_openid)

    async def ban_many(self, member_openids: Sequence[str]) -> MemberBlacklistOpReturn:
        return await self.admin.ban_many(self.group_openid, member_openids)

    async def unban(self, member_openid: str) -> MemberBlacklistOpReturn:
        return await self.admin.unban(self.group_openid, member_openid)

    async def unban_many(
        self, member_openids: Sequence[str]
    ) -> MemberBlacklistOpReturn:
        return await self.admin.unban_many(self.group_openid, member_openids)

    # --- 6. Join Requests & Message Recall ---

    async def list_join_requests(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> JoinRequestListReturn:
        return await self.admin.list_join_requests(
            self.group_openid, cursor=cursor, limit=limit
        )

    def iter_join_requests(
        self, *, limit: int | None = None
    ) -> AsyncIterator[JoinRequest]:
        return self.admin.iter_join_requests(self.group_openid, limit=limit)

    async def get_all_join_requests(
        self, *, limit: int | None = None
    ) -> list[JoinRequest]:
        return await self.admin.get_all_join_requests(self.group_openid, limit=limit)

    async def approve_join(
        self, member_openid: str, *, join_request_id: str | None = None
    ) -> None:
        await self.admin.approve_join(
            self.group_openid, member_openid, join_request_id=join_request_id
        )

    async def reject_join(
        self,
        member_openid: str,
        *,
        join_request_id: str | None = None,
        reason: str | None = None,
        add_to_blacklist: bool = False,
    ) -> None:
        await self.admin.reject_join(
            self.group_openid,
            member_openid,
            join_request_id=join_request_id,
            reason=reason,
            add_to_blacklist=add_to_blacklist,
        )

    async def recall(self, message_id: str) -> None:
        await self.admin.recall(self.group_openid, message_id)
