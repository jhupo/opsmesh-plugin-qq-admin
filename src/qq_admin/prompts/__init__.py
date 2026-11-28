"""Prompt loader reading structured prompt files from src/qq_admin/prompts/."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def _load_file(name: str) -> dict[str, Any]:
    with (PROMPTS_DIR / name).open("rb") as fp:
        return tomllib.load(fp)


class PromptCatalog:
    """Typed accessor over prompt files in qq_admin/prompts/."""

    def __init__(self) -> None:
        self._jev = _load_file("jev.toml")
        self._jev_guards = _load_file("jev_guards.toml")
        self._decision = _load_file("decision_agent.toml")
        self._reply = _load_file("reply_agent.toml")
        self._notices = _load_file("notices.toml")

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

    # ---- Jev join & guards ----
    def jev_join(self, key: str) -> str:
        return str(self._jev_guards.get("join_request", {}).get(key, ""))

    def jev_guard(self, key: str) -> str:
        return str(self._jev_guards.get("guards", {}).get(key, ""))

    # ---- DecisionAgent ----
    def role_policy(self, bot_role: str) -> str:
        return str(self._decision.get(f"role_policy_{bot_role}", ""))

    def planner_prompt(self, mode: str, **values: Any) -> str:
        return str(self._decision.get(mode, "")).format(**values)

    # ---- ReplyAgent ----
    def composer_persona(self) -> str:
        return str(self._reply.get("persona", "")).strip()

    def composer_instructions(self, **values: Any) -> str:
        return str(self._reply.get("instructions", "")).format(**values)

    def fake_claim_patterns(self) -> list[str]:
        return list(self._reply.get("fake_claim_patterns", []))

    def fake_deny_flags(self) -> list[str]:
        return list(self._reply.get("fake_deny_flags", []))

    def legit_reason_flags(self) -> list[str]:
        return list(self._reply.get("legit_reason_flags", []))

    # ---- Notices ----
    def format_fallback(self, key: str, **values: Any) -> str:
        template = str(self._notices.get(key, key))
        return template.format(**values) if values else template


__all__ = ["PROMPTS_DIR", "PromptCatalog"]
