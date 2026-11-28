"""Smoke tests for modular package exports, PluginMetadata, and prompts.toml."""

from unittest.mock import AsyncMock

from typesafe_sdk import AsyncTypeSafeClient

import qq_admin


def test_qq_admin_package_exports_and_injectable_typesafe_client() -> None:
    assert qq_admin.__version__ is not None
    assert qq_admin.__plugin_meta__.type == "application"
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}
    assert qq_admin.AsyncTypeSafeClient is AsyncTypeSafeClient

    prompts = qq_admin.load_prompts()
    assert "jev" in prompts
    assert isinstance(prompts["jev"]["incoming"]["violation_severity_criteria"], list)
    assert "decision_agent" in prompts
    assert "reply_agent" in prompts
    assert "fallback_messages" in prompts

    injected = AsyncMock(spec=AsyncTypeSafeClient)
    runtime = qq_admin.configure(qq_admin.QQAdminConfig(), jev_client=injected)
    assert qq_admin.get_runtime() is runtime
    assert runtime.jev_client is injected
    assert len(qq_admin.MODERATION_TOOLS) == 9
