"""Smoke test for `qq_admin` top-level exports."""

import qq_admin


def test_qq_admin_exports() -> None:
    assert qq_admin.__version__ is not None
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}
    for name in (
        "QQGroupAdmin",
        "QQGroupScope",
        "GroupAdmin",
        "CurrentGroup",
        "parse_mute_duration",
        "can_manage_member",
        "ensure_can_manage",
        "extract_group_openid",
        "QQAdminError",
        "BotNotAdminError",
        "HierarchyError",
        "GroupTargetRequiredError",
    ):
        assert hasattr(qq_admin, name)
