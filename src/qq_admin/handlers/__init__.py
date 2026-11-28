"""OpsMesh event and command handler registration package."""

from .commands import handle_admin_console as handle_admin_console
from .commands import register_commands as register_commands
from .events import handle_group_message_event as handle_group_message_event
from .events import handle_group_notice_event as handle_group_notice_event
from .events import register_event_handlers as register_event_handlers
