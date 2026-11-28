"""Smoke test for `qq_admin` package exports and core subpackages."""

import qq_admin
import qq_admin.matchers
import qq_admin.services
import qq_admin.store

PUBLIC_API_FUNCTIONS = (
    "set_group_enabled",
    "warn_member",
    "clear_warnings",
    "mute_member",
    "unmute_member",
    "get_mute_setting",
    "kick_member",
    "recall_message",
    "list_blacklist",
    "add_blacklist",
    "remove_blacklist",
    "get_member",
    "list_members",
    "list_join_requests",
    "approve_join_request",
    "decline_join_request",
    "get_group_info",
    "get_bot_state",
    "get_audit_log",
)


def test_qq_admin_skeleton_import() -> None:
    assert qq_admin.__version__ is not None
    for subpkg in (qq_admin.store, qq_admin.services, qq_admin.matchers):
        assert subpkg.__doc__
    for fn_name in PUBLIC_API_FUNCTIONS:
        assert callable(getattr(qq_admin, fn_name))
