"""Smoke test for `qq_admin` package and all 18 standalone async API modules."""

import importlib

import qq_admin
import qq_admin.api
import qq_admin.matchers
import qq_admin.services
import qq_admin.store

STANDALONE_API_MODULES = (
    "qq_admin.api.warn_member",
    "qq_admin.api.clear_warnings",
    "qq_admin.api.mute_member",
    "qq_admin.api.unmute_member",
    "qq_admin.api.get_mute_setting",
    "qq_admin.api.kick_member",
    "qq_admin.api.recall_message",
    "qq_admin.api.list_blacklist",
    "qq_admin.api.add_blacklist",
    "qq_admin.api.remove_blacklist",
    "qq_admin.api.get_member",
    "qq_admin.api.list_members",
    "qq_admin.api.list_join_requests",
    "qq_admin.api.approve_join_request",
    "qq_admin.api.decline_join_request",
    "qq_admin.api.get_group_info",
    "qq_admin.api.get_bot_state",
    "qq_admin.api.get_audit_log",
)


def test_qq_admin_skeleton_import() -> None:
    assert qq_admin.__version__ is not None
    for subpkg in (
        qq_admin.store,
        qq_admin.services,
        qq_admin.api,
        qq_admin.matchers,
    ):
        assert subpkg.__doc__
    for module_name in STANDALONE_API_MODULES:
        mod = importlib.import_module(module_name)
        assert mod.__doc__
