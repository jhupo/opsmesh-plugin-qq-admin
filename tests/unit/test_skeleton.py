"""Smoke tests for modular package exports, PluginMetadata, and prompts.toml."""

from unittest.mock import AsyncMock

import qq_admin


def test_qq_admin_package_exports_and_injectable_jev() -> None:
    assert qq_admin.__version__ is not None
    assert qq_admin.__plugin_meta__.type == "application"
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}

    prompts = qq_admin.load_prompts()
    assert "jev" in prompts
    assert "decision_agent" in prompts
    assert "reply_agent" in prompts
    assert "fallback_messages" in prompts

    injected = qq_admin.JevClient(
        qq_admin.JevConfig(enabled=True), sdk_client=AsyncMock()
    )
    runtime = qq_admin.configure(qq_admin.QQAdminConfig(), jev_client=injected)
    assert qq_admin.get_runtime() is runtime
    assert runtime.jev_client is injected
    assert runtime.jev_client.is_ready is True
    assert len(qq_admin.MODERATION_TOOLS) == 9
