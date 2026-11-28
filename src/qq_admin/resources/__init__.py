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
    """Typed accessor over externalized TOML prompt and message templates."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: str | Path = "") -> "PromptCatalog":
        target = Path(path) if str(path).strip() else DEFAULT_PROMPTS_PATH
        return cls(_read_toml(str(target.resolve())))

    @property
    def jev(self) -> dict[str, Any]:
        return self._data.get("jev", {})

    @property
    def planner(self) -> dict[str, Any]:
        return self._data.get("planner", {})

    @property
    def composer(self) -> dict[str, Any]:
        return self._data.get("composer", {})

    def format_fallback(self, key: str, **kwargs: Any) -> str:
        template = str(self._data.get("fallback", {}).get(key, key))
        return template.format(**kwargs) if kwargs else template


__all__ = ["DEFAULT_CONFIG_PATH", "DEFAULT_PROMPTS_PATH", "PromptCatalog"]
