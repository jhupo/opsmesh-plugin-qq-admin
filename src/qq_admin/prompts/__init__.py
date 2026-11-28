"""Prompt loader reading Markdown templates and TOML configs from prompts/."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def _load_toml(name: str) -> dict[str, Any]:
    with (PROMPTS_DIR / name).open("rb") as fp:
        return tomllib.load(fp)


@lru_cache(maxsize=16)
def _load_markdown(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


class PromptCatalog:
    """Typed accessor over Markdown role templates and TOML criteria in prompts/."""

    def __init__(self) -> None:
        self._jev = _load_toml("jev.toml")
        self._jev_guards = _load_toml("jev_guards.toml")
        self._notices = _load_toml("notices.toml")
        self._reply_md = _load_markdown("reply_agent.md")
        self._decision_auto_md = _load_markdown("decision_auto.md")
        self._decision_admin_md = _load_markdown("decision_admin.md")

    @classmethod
    def load(cls) -> "PromptCatalog":
        return cls()

    # ---- Jev fixed safety questions ----
    def jev_questions(self) -> dict[str, str]:
        return dict(self._jev.get("questions", {}))

    def jev_severity_instructions(self) -> str:
        return str(self._jev.get("severity_instructions", ""))

    def jev_severity_criteria(self) -> list[str]:
        return list(self._jev.get("severity_criteria", []))

    # ---- Jev join & optional tool judge ----
    def jev_join(self, key: str) -> str:
        return str(self._jev_guards.get("join_request", {}).get(key, ""))

    def jev_guard(self, key: str) -> str:
        return str(self._jev_guards.get("guards", {}).get(key, ""))

    # ---- DecisionAgent (.md templates) ----
    def role_policy(self, bot_role: str) -> str:
        return str(self._notices.get("role_policy", {}).get(bot_role, ""))

    def decision_prompt(self, mode: str, **values: Any) -> str:
        template = (
            self._decision_admin_md
            if mode == "admin_command"
            else self._decision_auto_md
        )
        return template.format(**values)

    # ---- ReplyAgent (.md template) ----
    def reply_template(self) -> str:
        return self._reply_md

    def reply_prompt(self, **values: Any) -> str:
        return self._reply_md.format(**values)

    def fake_claim_patterns(self) -> list[str]:
        return list(self._notices.get("reply_guard", {}).get("fake_claim_patterns", []))

    def fake_deny_flags(self) -> list[str]:
        return list(self._notices.get("reply_guard", {}).get("fake_deny_flags", []))

    def legit_reason_flags(self) -> list[str]:
        return list(self._notices.get("reply_guard", {}).get("legit_reason_flags", []))

    # ---- Fallback notices ----
    def format_fallback(self, key: str, **values: Any) -> str:
        template = str(self._notices.get("fallback", {}).get(key, key))
        return template.format(**values) if values else template


__all__ = ["PROMPTS_DIR", "PromptCatalog"]
