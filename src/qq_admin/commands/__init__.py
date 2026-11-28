"""Declarative Official QQ v2 slash command suite (21 commands)."""

from . import actions as _actions  # noqa: F401
from . import console as _console  # noqa: F401
from . import queries as _queries  # noqa: F401
from .registry import COMMAND_ROUTES as COMMAND_ROUTES
from .registry import CommandContext as CommandContext
from .registry import CommandRoute as CommandRoute
from .registry import bind_commands as bind_commands
from .registry import command as command
from .registry import dispatch_command as dispatch_command
