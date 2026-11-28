"""Unit tests for TOML configuration, PromptCatalog, and AdminRuntime wiring."""

from unittest.mock import AsyncMock

from typesafe_sdk import AsyncTypeSafeClient

import qq_admin


def test_config_from_toml_and_clean_exports() -> None:
    assert qq_admin.__version__ is not None
    assert qq_admin.__plugin_meta__.type == "application"
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}

    cfg = qq_admin.AdminConfig.from_toml(qq_admin.DEFAULT_CONFIG_PATH)
    assert cfg.plugin.enabled is True
    assert cfg.jev.model == "jev-1"
    assert len(cfg.escalation.steps) == 3

    env_cfg = qq_admin.Config(qq_admin_config=str(qq_admin.DEFAULT_CONFIG_PATH))
    resolved = env_cfg.resolve()
    assert resolved.moderation.recent_context_size == 20

    catalog = qq_admin.PromptCatalog.load()
    assert isinstance(catalog.jev["incoming"]["violation_severity_criteria"], list)
    assert "auto_moderate" in catalog.planner
    assert "persona" in catalog.composer

    injected_jev = AsyncMock(spec=AsyncTypeSafeClient)
    runtime = qq_admin.configure(cfg, jev_client=injected_jev)
    assert qq_admin.get_runtime() is runtime
    assert runtime.jev.client is injected_jev
    assert runtime.jev.is_active is True

    tool_names = [t.name for t in qq_admin.GROUP_ADMIN_TOOLS]
    assert all(not name.startswith("tool_") for name in tool_names)
    assert "mute_member" in tool_names
    assert "kick_member" in tool_names
    assert len(qq_admin.COMMAND_ROUTES) == 21
