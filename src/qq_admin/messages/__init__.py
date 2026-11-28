"""Inbound entries: group messages and group lifecycle events."""

from qq_admin.manager import ServiceManager

from .group_events import bind_group_events, handle_group_event
from .group_message import bind_group_message, handle_group_message


def bind_messages(manager: ServiceManager) -> None:
    bind_group_message(manager)
    bind_group_events(manager)


__all__ = ["bind_messages", "handle_group_event", "handle_group_message"]
