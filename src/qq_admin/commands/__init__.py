"""Slash commands registered directly on OpsMesh."""

from qq_admin.manager import ServiceManager

from .actions import ACTION_COMMANDS, bind_action_commands, run_action
from .admin import SUBCOMMANDS, bind_admin_commands, run_admin
from .queries import QUERY_COMMANDS, bind_query_commands, run_query


def bind_commands(manager: ServiceManager) -> None:
    bind_admin_commands(manager)
    bind_action_commands(manager)
    bind_query_commands(manager)


__all__ = [
    "ACTION_COMMANDS",
    "QUERY_COMMANDS",
    "SUBCOMMANDS",
    "bind_commands",
    "run_action",
    "run_admin",
    "run_query",
]
