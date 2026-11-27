"""Shared command matcher helpers and top-level matcher module loader."""

from collections.abc import Awaitable
import importlib
import re
from typing import Any

from opsmesh.permission import SUPERUSER
from qq import GROUP_ADMIN, GROUP_OWNER, Gateway, GroupMessageEvent, Message

from qq_admin.api import get_services
from qq_admin.context import AdminContext, ModerationOutcome
from qq_admin.exception import QQAdminError
from qq_admin.services import AdminServices
from qq_admin.typing import AuditSource

ADMIN_PERMISSION = SUPERUSER | GROUP_OWNER | GROUP_ADMIN

_DURATION_RE = re.compile(r"^(\d+)([smhdSMHD]?)$")
_UNIT_SECONDS = {"": 60, "s": 1, "m": 60, "h": 3600, "d": 86400}
_MATCHER_MODULES = (
    "qq_admin.matchers.panel",
    "qq_admin.matchers.moderation",
    "qq_admin.matchers.blacklist",
    "qq_admin.matchers.approval",
    "qq_admin.matchers.query",
)


def parse_duration_seconds(token: str, *, default: int = 600) -> int:
    """Parse human-friendly duration tokens such as '10m', '2h', '300s', '1d'."""
    match = _DURATION_RE.fullmatch(token.strip())
    if not match:
        return default
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def extract_target_and_rest(args: Message) -> tuple[str, list[str]]:
    """Extract target member_openid from mention_user segment or first plain token."""
    mention_id = next(
        (
            str(seg.data["user_id"])
            for seg in args
            if seg.type == "mention_user" and seg.data.get("user_id")
        ),
        "",
    )
    tokens = args.extract_plain_text().split()
    if mention_id:
        return mention_id, tokens
    return (tokens[0], tokens[1:]) if tokens else ("", [])


def make_command_context(
    gateway: Gateway,
    event: GroupMessageEvent,
    *,
    services: AdminServices | None = None,
) -> AdminContext:
    """Construct an AdminContext from an inbound QQ group message event."""
    svc = services if services is not None else get_services()
    operator = svc.identity.resolve_operator(
        event.get_user_id(), member_role=event.author.member_role
    )
    return AdminContext(
        gateway=gateway,
        group_openid=event.group_openid,
        operator=operator,
        source=AuditSource.COMMAND,
    )


async def finish_outcome(matcher: Any, coro: Awaitable[ModerationOutcome]) -> None:
    """Await a moderation coroutine and reply with summary or structured error."""
    try:
        outcome = await coro
    except QQAdminError as exc:
        await matcher.finish(f"[{exc.code}] {exc.message}")
    await matcher.finish(outcome.summary)


def register_all_matchers(_services: AdminServices | None = None) -> None:
    """Import all top-level OpsMesh matcher modules once."""
    for mod_name in _MATCHER_MODULES:
        importlib.import_module(mod_name)


__all__ = [
    "ADMIN_PERMISSION",
    "extract_target_and_rest",
    "finish_outcome",
    "make_command_context",
    "parse_duration_seconds",
    "register_all_matchers",
]
