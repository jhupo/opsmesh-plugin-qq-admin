"""Externalized TOML prompt catalog and template formatter."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

DEFAULT_PROMPTS_PATH = Path(__file__).with_name("prompts.toml")
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


@lru_cache(maxsize=4)
def _read_toml(resolved_path: str) -> dict[str, Any]:
    with Path(resolved_path).open("rb") as fp:
        return tomllib.load(fp)


class PromptCatalog:
    """Typed accessor over localized prompt, criteria, and notice templates."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PromptCatalog":
        target = Path(path) if path and str(path).strip() else DEFAULT_PROMPTS_PATH
        return cls(_read_toml(str(target.resolve())))

    def _section(self, *keys: str) -> dict[str, Any]:
        node: Any = self._data
        for key in keys:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        return node if isinstance(node, dict) else {}

    # ---- Jev ----
    def jev_incoming(self, key: str) -> str:
        return str(self._section("jev", "incoming").get(key, ""))

    def jev_incoming_criteria(self, key: str) -> dict[str, str]:
        return dict(self._section("jev", "incoming").get(key, {}))

    def jev_incoming_list(self, key: str) -> list[str]:
        return list(self._section("jev", "incoming").get(key, []))

    def jev_join(self, key: str) -> str:
        return str(self._section("jev", "join_request").get(key, ""))

    def jev_guard(self, key: str) -> str:
        return str(self._section("jev", "guards").get(key, ""))

    # ---- DecisionAgent ----
    def role_policy(self, bot_role: str) -> str:
        return str(self._section("planner").get(f"role_policy_{bot_role}", ""))

    def planner_prompt(self, mode: str, **values: Any) -> str:
        return str(self._section("planner").get(mode, "")).format(**values)

    # ---- ReplyAgent ----
    def composer_persona(self) -> str:
        return str(self._section("composer").get("persona", "")).strip()

    def composer_instructions(self, **values: Any) -> str:
        return str(self._section("composer").get("instructions", "")).format(**values)

    def fake_claim_patterns(self) -> list[str]:
        return list(self._section("composer").get("fake_claim_patterns", []))

    def fake_deny_flags(self) -> list[str]:
        return list(self._section("composer").get("fake_deny_flags", []))

    def legit_reason_flags(self) -> list[str]:
        return list(self._section("composer").get("legit_reason_flags", []))

    # ---- Fallback notices ----
    def format_fallback(self, key: str, **values: Any) -> str:
        template = str(self._section("fallback").get(key, key))
        return template.format(**values) if values else template


__all__ = ["DEFAULT_CONFIG_PATH", "DEFAULT_PROMPTS_PATH", "PromptCatalog"]
