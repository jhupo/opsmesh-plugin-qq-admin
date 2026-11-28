"""Tests for Config, diff-only multi-group ConfigStore, and pure Markdown prompts."""

from pathlib import Path

import pytest

import qq_admin
from qq_admin import (
    APPROVAL,
    CONFIG_STORE,
    GROUP_ADMIN,
    MANAGER,
    PROMPTS_DIR,
    SAFEGUARD,
    SAFETY_FIELDS,
    Config,
    ConfigError,
    ConfigStore,
    load_md,
    load_toml,
)

EXPECTED_SAFETY_CATEGORIES = set(SAFETY_FIELDS)


def test_config_defaults_and_markdown_prompts() -> None:
    cfg = Config()
    assert cfg.jev_model == "jev-1"
    assert cfg.model == "gpt-5-mini"
    assert cfg.reasoning_effort == "low"
    assert cfg.timeout_seconds == 30.0
    assert cfg.default_group_enabled is False

    assert qq_admin.__plugin_meta__.type == "application"
    assert qq_admin.__plugin_meta__.supported_adapters == {"qq"}
    assert GROUP_ADMIN is not None

    assert PROMPTS_DIR.is_dir()
    assert not (PROMPTS_DIR / "decision_auto.md").exists()
    assert not (PROMPTS_DIR / "decision_admin.md").exists()
    assert not (PROMPTS_DIR / "jev_guards.toml").exists()

    content = (PROMPTS_DIR / "reply_agent.md").read_text(encoding="utf-8")
    assert "<role>" not in content
    assert "<context>" not in content
    assert "## " in content

    jev_data = load_toml("jev.toml")
    assert set(jev_data["questions"].keys()) == EXPECTED_SAFETY_CATEGORIES
    assert jev_data["severity_criteria"]
    assert jev_data["join_request_instructions"]

    reply_rendered = load_md(
        "reply_agent.md",
        group_id="G1",
        bot_role="admin",
        scenario="auto_moderation",
        actor_id="U1",
        actor_role="member",
        target_id="U1",
        categories="advertising",
        mute_count=1,
        mute_limit=10,
        kick_count=0,
        kick_limit=3,
        group_rule_hint="No commercial links",
    )
    assert "G1" in reply_rendered
    assert "advertising" in reply_rendered
    assert "No commercial links" in reply_rendered


def test_diff_only_group_overrides_reset_and_onboarding_mode(tmp_path: Path) -> None:
    toml_file = tmp_path / "config.toml"
    MANAGER.setup(Config(), store=ConfigStore.from_toml(toml_file))

    assert not MANAGER.is_group_enabled("G1")
    MANAGER.set_group_enabled("G1", True)
    assert MANAGER.is_group_enabled("G1")
    assert not MANAGER.is_group_enabled("G2")

    assert SAFEGUARD.config("G1").max_mute_duration == 3600
    updated = SAFEGUARD.update_config("G1", "max_mute_duration", "1800")
    assert updated.max_mute_duration == 1800
    assert SAFEGUARD.config("G2").max_mute_duration == 3600

    # Only the modified field is persisted in the per-group section
    raw_g1_sg = CONFIG_STORE.raw_data()["groups"]["G1"]["safeguard"]
    assert raw_g1_sg == {"max_mute_duration": 1800}

    # Global baseline changes propagate to unoverridden fields in G1
    SAFEGUARD.update_config(None, "daily_mute_limit", "25")
    assert SAFEGUARD.config("G1").daily_mute_limit == 25
    assert SAFEGUARD.config("G1").max_mute_duration == 1800

    # Resetting field override restores inheritance from global config
    SAFEGUARD.reset_config("G1", "max_mute_duration")
    assert SAFEGUARD.config("G1").max_mute_duration == 3600
    assert "safeguard" not in CONFIG_STORE.raw_data()["groups"]["G1"]

    APPROVAL.update_config("G1", "enabled", "true")
    APPROVAL.update_config("G1", "default_action", "approve")

    # Auto-onboard mode (default_group_enabled=True) with explicit per-group off
    MANAGER.setup(
        Config(default_group_enabled=True),
        store=ConfigStore.from_toml(toml_file),
    )
    assert MANAGER.is_group_enabled("G1")
    assert MANAGER.is_group_enabled("UNSEEN_GROUP")
    MANAGER.set_group_enabled("G2", False)
    assert not MANAGER.is_group_enabled("G2")
    assert APPROVAL.config("G1").enabled is True
    assert APPROVAL.config("G1").default_action == "approve"

    with pytest.raises(ConfigError):
        SAFEGUARD.update_config("G1", "nonexistent", "123")
    with pytest.raises(ConfigError):
        SAFEGUARD.update_config("G1", "max_mute_duration", "not-an-int")
    with pytest.raises(ConfigError):
        SAFEGUARD.reset_config("G1", "nonexistent")
