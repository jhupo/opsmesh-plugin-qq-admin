"""Simple cached readers for Markdown templates and TOML prompt data."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def load_toml(name: str) -> dict[str, Any]:
    with (PROMPTS_DIR / name).open("rb") as fp:
        return tomllib.load(fp)


@lru_cache(maxsize=16)
def read_md(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def load_md(name: str, **values: Any) -> str:
    template = read_md(name)
    return template.format(**values) if values else template


def notice(key: str, **values: Any) -> str:
    template = str(load_toml("notices.toml").get("fallback", {}).get(key, key))
    return template.format(**values) if values else template


__all__ = ["PROMPTS_DIR", "load_md", "load_toml", "notice", "read_md"]
