"""Tests for Config, Claude-style Markdown prompts, and module-owned configs."""

from pathlib import Path

import pytest

import qq_admin
from qq_admin import (
    APPROVAL,
    CATALOG,
    MANAGER,
    PROMPTS_DIR,
    SAFEGUARD,
    SAFETY_FIELDS,
    Config,
    ConfigError,
    ConfigStore,
)

EXPECTED_SAFETY_CATEGORIES = set(SAFETY_FIELDS)


def test_config_defaults_and_markdown_prompts() -> None:
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
    for fname in ("reply_agent.md", "decision_auto.md", "decision_admin.md"):
        assert (PROMPTS_DIR / fname).is_file()

    assert set(CATALOG.jev_questions().keys()) == EXPECTED_SAFETY_CATEGORIES
    assert CATALOG.jev_severity_criteria()

    # Verify all 3 Markdown prompt templates format cleanly with XML tags & examples
    reply_rendered = CATALOG.reply_prompt(
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
    )
    assert "<role>" in reply_rendered
    assert "<persona>" in reply_rendered
    assert "<examples>" in reply_rendered

    auto_rendered = CATALOG.decision_prompt(
        "auto_moderate",
        group_id="G1",
        bot_role="admin",
        role_policy="admin policy",
        member_id="U1",
        sender_role="member",
        recent_ops=0,
        jev_summary="categories=['advertising']",
    )
    assert "<tools>" in auto_rendered
    assert "<examples>" in auto_rendered

    admin_rendered = CATALOG.decision_prompt(
        "admin_command",
        group_id="G1",
        bot_role="owner",
        role_policy="owner policy",
        member_id="ADMIN_1",
        sender_role="owner",
    )
    assert "<tools>" in admin_rendered
    assert "<examples>" in admin_rendered


def test_module_owned_config_persistence_and_group_isolation(tmp_path: Path) -> None:
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

    APPROVAL.update_config("G1", "enabled", "true")
    APPROVAL.update_config("G1", "default_action", "approve")

    MANAGER.setup(Config(), store=ConfigStore.from_toml(toml_file))
    assert MANAGER.is_group_enabled("G1")
    assert SAFEGUARD.config("G1").max_mute_duration == 1800
    assert APPROVAL.config("G1").enabled is True
    assert APPROVAL.config("G1").default_action == "approve"

    with pytest.raises(ConfigError):
        SAFEGUARD.update_config("G1", "nonexistent", "123")
    with pytest.raises(ConfigError):
        SAFEGUARD.update_config("G1", "max_mute_duration", "not-an-int")
