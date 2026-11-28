"""Module-agnostic TOML persistence store with per-group diff overrides."""

from copy import deepcopy
import json
import os
from pathlib import Path
from threading import RLock
import tomllib
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from .exception import ConfigError


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _diff_dict(values: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(val) for key, val in values.items() if baseline.get(key) != val
    }


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
    """Thread-safe TOML configuration store with diff-only per-group overrides."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        path: str | Path | None = None,
    ) -> None:
        self._lock = RLock()
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
        with self._lock:
            return deepcopy(self._data)

    def load_section(
        self,
        namespace: str,
        *,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Load global defaults merged with optional per-group overrides."""
        with self._lock:
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
        defaults: dict[str, Any] | None = None,
    ) -> None:
        """Persist a module's config globally or store diff-only per-group overrides."""
        with self._lock:
            if group_id:
                global_sec = self._data.get(namespace)
                base_global = (
                    deepcopy(global_sec) if isinstance(global_sec, dict) else {}
                )
                baseline = (
                    _deep_merge(defaults, base_global)
                    if defaults is not None
                    else base_global
                )
                diff = _diff_dict(values, baseline) if defaults is not None else values
                groups = self._data.setdefault("groups", {})
                group_sec = groups.setdefault(group_id, {})
                if diff:
                    group_sec[namespace] = deepcopy(diff)
                else:
                    group_sec.pop(namespace, None)
                    if not group_sec:
                        groups.pop(group_id, None)
            else:
                payload = (
                    _diff_dict(values, defaults) if defaults is not None else values
                )
                if payload:
                    self._data[namespace] = deepcopy(payload)
                else:
                    self._data.pop(namespace, None)
            self.flush()

    def reset_section(
        self,
        namespace: str,
        field_name: str | None = None,
        *,
        group_id: str,
    ) -> None:
        """Remove a field override or an entire module override for one group."""
        with self._lock:
            groups = self._data.get("groups")
            if not isinstance(groups, dict):
                return
            group_sec = groups.get(group_id)
            if not isinstance(group_sec, dict):
                return
            if field_name:
                mod_sec = group_sec.get(namespace)
                if isinstance(mod_sec, dict):
                    mod_sec.pop(field_name, None)
                    if not mod_sec:
                        group_sec.pop(namespace, None)
            else:
                group_sec.pop(namespace, None)
            if not group_sec:
                groups.pop(group_id, None)
            self.flush()

    def is_group_enabled(self, group_id: str, *, default: bool = False) -> bool:
        with self._lock:
            groups = self._data.get("groups")
            if isinstance(groups, dict):
                group_sec = groups.get(group_id)
                if isinstance(group_sec, dict) and "enabled" in group_sec:
                    return bool(group_sec["enabled"])
            return bool(default)

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        with self._lock:
            groups = self._data.setdefault("groups", {})
            group_sec = groups.setdefault(group_id, {})
            group_sec["enabled"] = bool(enabled)
            self.flush()

    def known_groups(self) -> list[str]:
        with self._lock:
            groups = self._data.get("groups")
            if not isinstance(groups, dict):
                return []
            return sorted(gid for gid, sec in groups.items() if isinstance(sec, dict))

    def enabled_groups(self, *, default: bool = False) -> list[str]:
        with self._lock:
            return [
                gid
                for gid in self.known_groups()
                if self.is_group_enabled(gid, default=default)
            ]

    def reset(
        self,
        data: dict[str, Any] | None = None,
        *,
        path: str | Path | None = None,
    ) -> "ConfigStore":
        """Replace backing data/path in place so global modules stay bound."""
        with self._lock:
            self._path = Path(path) if path else None
            if data is not None:
                self._data = deepcopy(data)
            elif self._path is not None and self._path.is_file():
                with self._path.open("rb") as fp:
                    self._data = tomllib.load(fp)
            else:
                self._data = {}
            return self

    def flush(self) -> None:
        with self._lock:
            if self._path is None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
            tmp_path.write_text(dump_toml(self._data), encoding="utf-8")
            os.replace(tmp_path, self._path)


CONFIG_STORE = ConfigStore()

__all__ = ["CONFIG_STORE", "ConfigStore", "dump_toml", "parse_field_value"]
