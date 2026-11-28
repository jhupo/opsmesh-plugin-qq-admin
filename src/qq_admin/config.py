"""Base model configs (Jev, DecisionAgent, ReplyAgent) and TOML ConfigStore."""

from copy import deepcopy
import json
from pathlib import Path
import tomllib
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .exception import ConfigError

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class JevConfig(BaseModel):
    """Connection settings for TypeSafe AI Jev (System 1)."""

    api_key: SecretStr = Field(
        default=SecretStr(""),
        description="TypeSafe API key (or TYPESAFE_API_KEY env).",
    )
    model: str = Field(default="jev-1", description="TypeSafe System One model name.")
    proxy: str = Field(default="", description="Optional HTTP/SOCKS5 proxy URL.")
    timeout_seconds: float = Field(
        default=10.0, gt=0, description="Request timeout in seconds."
    )

    @property
    def secret_value(self) -> str:
        return self.api_key.get_secret_value().strip()


class OpenAIConfig(BaseModel):
    """Shared OpenAI Responses API endpoint credentials."""

    api_key: SecretStr = Field(
        default=SecretStr(""),
        description="OpenAI or compatible Responses endpoint API key.",
    )
    base_url: str = Field(default="", description="Optional custom Responses base URL.")
    timeout_seconds: float = Field(default=30.0, gt=0)

    @property
    def secret_value(self) -> str:
        return self.api_key.get_secret_value().strip()


class BaseAgentConfig(BaseModel):
    """Shared per-agent model behavior settings (Responses API)."""

    model: str = Field(default="gpt-5-mini", description="Target LLM model name.")
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="Optional reasoning effort level (none/minimal/low/medium/high).",
    )
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Optional sampling temperature."
    )
    max_turns: int = Field(default=6, ge=1, le=16)


class DecisionAgentConfig(BaseAgentConfig):
    """Configuration for DecisionAgent (tool-calling moderation decisions)."""

    temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    max_turns: int = Field(default=6, ge=1, le=16)


class ReplyAgentConfig(BaseAgentConfig):
    """Configuration for ReplyAgent (persona-driven dynamic replies)."""

    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_turns: int = Field(default=2, ge=1, le=8)
    persona: str = Field(
        default="", description="Optional persona overriding prompts.toml."
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _toml_key(key: str) -> str:
    if key and all(ch.isalnum() or ch in ("_", "-") for ch in key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = [f"{_toml_key(str(k))} = {_toml_value(v)}" for k, v in value.items()]
        return "{ " + ", ".join(pairs) + " }"
    return json.dumps(str(value), ensure_ascii=False)


def dump_toml(data: dict[str, Any]) -> str:
    """Serialize a nested configuration dictionary into clean TOML text."""
    lines: list[str] = []

    def _emit_table(table: dict[str, Any], prefix: list[str]) -> None:
        scalars: list[tuple[str, Any]] = []
        subtables: list[tuple[str, dict[str, Any]]] = []
        table_arrays: list[tuple[str, list[dict[str, Any]]]] = []
        for k, v in table.items():
            if v is None:
                continue
            if isinstance(v, dict):
                subtables.append((k, v))
            elif isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                table_arrays.append((k, v))
            else:
                scalars.append((k, v))

        if prefix and (scalars or (not subtables and not table_arrays)):
            header = ".".join(_toml_key(part) for part in prefix)
            lines.append(f"[{header}]")
        for k, v in scalars:
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        if prefix and scalars:
            lines.append("")

        for k, items in table_arrays:
            arr_header = ".".join(_toml_key(part) for part in [*prefix, k])
            for item in items:
                lines.append(f"[[{arr_header}]]")
                for ik, iv in item.items():
                    if iv is not None:
                        lines.append(f"{_toml_key(ik)} = {_toml_value(iv)}")
                lines.append("")

        for k, sub in subtables:
            _emit_table(sub, [*prefix, k])

    _emit_table(data, [])
    return "\n".join(lines).rstrip() + "\n"


def parse_field_value(
    model_cls: type[BaseModel],
    field_name: str,
    raw_value: str,
) -> Any:
    """Coerce a CLI string value according to a Pydantic model field annotation."""
    field = model_cls.model_fields.get(field_name)
    if field is None:
        raise ConfigError(f"Unknown config field: {field_name}")

    text = raw_value.strip()
    annotation = field.annotation
    origin = get_origin(annotation)

    if annotation is bool:
        lower = text.lower()
        if lower in {"true", "1", "yes", "on"}:
            return True
        if lower in {"false", "0", "no", "off"}:
            return False
        raise ConfigError(f"Invalid boolean for {field_name}: {raw_value}")
    if annotation is int:
        try:
            return int(text)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer for {field_name}: {raw_value}") from exc
    if annotation is float:
        try:
            return float(text)
        except ValueError as exc:
            raise ConfigError(f"Invalid float for {field_name}: {raw_value}") from exc
    if origin is list:
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ConfigError(f"Expected list for {field_name}")
            return parsed
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]
    if origin is Literal:
        allowed = get_args(annotation)
        if text not in allowed:
            raise ConfigError(f"Invalid value for {field_name}; expected {allowed}")
        return text
    return text


class ConfigStore:
    """Module-agnostic configuration persistence store backed by TOML."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        path: str | Path | None = None,
    ) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, Any] = deepcopy(data) if data else {}

    @classmethod
    def from_toml(cls, path: str | Path) -> "ConfigStore":
        toml_path = Path(path)
        data: dict[str, Any] = {}
        if toml_path.is_file():
            with toml_path.open("rb") as fp:
                data = tomllib.load(fp)
        return cls(data, path=toml_path)

    @property
    def path(self) -> Path | None:
        return self._path

    def raw_data(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def load_section(
        self,
        namespace: str,
        *,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Load global defaults merged with optional per-group overrides."""
        global_sec = self._data.get(namespace)
        base = deepcopy(global_sec) if isinstance(global_sec, dict) else {}
        if not group_id:
            return base
        groups = self._data.get("groups")
        if not isinstance(groups, dict):
            return base
        group_sec = groups.get(group_id)
        if not isinstance(group_sec, dict):
            return base
        override = group_sec.get(namespace)
        if not isinstance(override, dict):
            return base
        return _deep_merge(base, override)

    def save_section(
        self,
        namespace: str,
        values: dict[str, Any],
        *,
        group_id: str | None = None,
    ) -> None:
        """Persist a module's config dict globally or for a specific group."""
        if group_id:
            groups = self._data.setdefault("groups", {})
            group_sec = groups.setdefault(group_id, {})
            group_sec[namespace] = deepcopy(values)
        else:
            self._data[namespace] = deepcopy(values)
        self.flush()

    def is_group_enabled(self, group_id: str) -> bool:
        groups = self._data.get("groups")
        if not isinstance(groups, dict):
            return False
        group_sec = groups.get(group_id)
        if not isinstance(group_sec, dict):
            return False
        return bool(group_sec.get("enabled", False))

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        groups = self._data.setdefault("groups", {})
        group_sec = groups.setdefault(group_id, {})
        group_sec["enabled"] = bool(enabled)
        self.flush()

    def enabled_groups(self) -> list[str]:
        groups = self._data.get("groups")
        if not isinstance(groups, dict):
            return []
        return sorted(
            gid
            for gid, sec in groups.items()
            if isinstance(sec, dict) and bool(sec.get("enabled", False))
        )

    def flush(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(dump_toml(self._data), encoding="utf-8")


class Config(BaseModel):
    """OpsMesh Driver config adapter for Jev, OpenAI, and both agents."""

    model_config = ConfigDict(extra="ignore")

    qq_admin_config: str = ""
    qq_admin_prompts: str = ""
    qq_admin_jev: JevConfig = Field(default_factory=JevConfig)
    qq_admin_openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    qq_admin_decision_agent: DecisionAgentConfig = Field(
        default_factory=DecisionAgentConfig
    )
    qq_admin_reply_agent: ReplyAgentConfig = Field(default_factory=ReplyAgentConfig)

    def build_store(
        self,
    ) -> tuple[
        JevConfig, OpenAIConfig, DecisionAgentConfig, ReplyAgentConfig, ConfigStore
    ]:
        if self.qq_admin_config.strip():
            store = ConfigStore.from_toml(self.qq_admin_config.strip())
            jev_raw = store.load_section("jev")
            oa_raw = store.load_section("openai")
            dec_raw = store.load_section("decision_agent")
            rep_raw = store.load_section("reply_agent")
            return (
                JevConfig.model_validate(jev_raw) if jev_raw else self.qq_admin_jev,
                OpenAIConfig.model_validate(oa_raw) if oa_raw else self.qq_admin_openai,
                DecisionAgentConfig.model_validate(dec_raw)
                if dec_raw
                else self.qq_admin_decision_agent,
                ReplyAgentConfig.model_validate(rep_raw)
                if rep_raw
                else self.qq_admin_reply_agent,
                store,
            )
        return (
            self.qq_admin_jev,
            self.qq_admin_openai,
            self.qq_admin_decision_agent,
            self.qq_admin_reply_agent,
            ConfigStore(),
        )


__all__ = [
    "BaseAgentConfig",
    "Config",
    "ConfigStore",
    "DecisionAgentConfig",
    "JevConfig",
    "OpenAIConfig",
    "ReasoningEffort",
    "ReplyAgentConfig",
    "dump_toml",
    "parse_field_value",
]
