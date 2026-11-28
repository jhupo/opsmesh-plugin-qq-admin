"""Tests for Config, prompt files in prompts/, and module-owned configs."""

from pathlib import Path

import pytest

import qq_admin
from qq_admin import (
    PROMPTS_DIR,
    SAFETY_FIELDS,
    Config,
    ConfigError,
    ConfigStore,
    PromptCatalog,
    ServiceManager,
)

EXPECTED_SAFETY_CATEGORIES = set(SAFETY_FIELDS)


def test_config_defaults_and_prompts_folder() -> None:
    cfg = Config()
    assert cfg.jev_model == "jev-1"
    assert cfg.model == "gpt-5-mini"
    assert cfg.reasoning_effort == "low"
    assert cfg.max_turns == 6
    assert cfg.timeout_seconds == 30.0

    assert qq_admin.__plugin_meta__.type == "application"
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}
    for tool in qq_admin.GROUP_ADMIN_TOOLS:
        assert not tool.name.startswith("tool_")

    assert PROMPTS_DIR.is_dir()
    assert (PROMPTS_DIR / "reply_agent.md").is_file()
    assert (PROMPTS_DIR / "decision_auto.md").is_file()
    assert (PROMPTS_DIR / "decision_admin.md").is_file()
    catalog = PromptCatalog.load()
    assert set(catalog.jev_questions().keys()) == EXPECTED_SAFETY_CATEGORIES
    assert catalog.jev_severity_criteria()
    assert catalog.reply_template()


def test_module_owned_config_persistence_and_group_isolation(tmp_path: Path) -> None:
    toml_file = tmp_path / "config.toml"
    store = ConfigStore.from_toml(toml_file)
    manager = ServiceManager(store=store)

    assert not manager.is_group_enabled("G1")
    manager.set_group_enabled("G1", True)
    assert manager.is_group_enabled("G1")
    assert not manager.is_group_enabled("G2")

    assert manager.safeguard.config("G1").max_mute_duration == 3600
    updated = manager.safeguard.update_config("G1", "max_mute_duration", "1800")
    assert updated.max_mute_duration == 1800
    assert manager.safeguard.config("G2").max_mute_duration == 3600

    manager.approval.update_config("G1", "enabled", "true")
    manager.approval.update_config("G1", "default_action", "approve")

    reloaded = ServiceManager(store=ConfigStore.from_toml(toml_file))
    assert reloaded.is_group_enabled("G1")
    assert reloaded.safeguard.config("G1").max_mute_duration == 1800
    assert reloaded.approval.config("G1").enabled is True
    assert reloaded.approval.config("G1").default_action == "approve"

    with pytest.raises(ConfigError):
        reloaded.safeguard.update_config("G1", "nonexistent", "123")
    with pytest.raises(ConfigError):
        reloaded.safeguard.update_config("G1", "max_mute_duration", "not-an-int")
