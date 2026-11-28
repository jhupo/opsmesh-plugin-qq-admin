"""Sliding-window warning tracker module with self-owned WarningConfig."""

import time

from pydantic import BaseModel, Field

from qq_admin.exception import ConfigError
from qq_admin.store import CONFIG_STORE, ConfigStore, parse_field_value


class WarningConfig(BaseModel):
    """Per-category sliding-window warning thresholds."""

    enabled: bool = True
    spam_threshold: int = Field(default=3, ge=1)
    spam_window_seconds: int = Field(default=600, ge=60)
    abuse_threshold: int = Field(default=1, ge=1)
    abuse_window_seconds: int = Field(default=3600, ge=60)
    ad_threshold: int = Field(default=1, ge=1)
    ad_window_seconds: int = Field(default=1800, ge=60)


class WarningModule:
    """Tracks per-member categorized warnings inside rolling time windows."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._warnings: dict[tuple[str, str, str], list[float]] = {}

    def config(self, group_id: str | None = None) -> WarningConfig:
        raw = self._store.load_section("warning", group_id=group_id)
        return WarningConfig.model_validate(raw)

    def update_config(
        self, group_id: str | None, key: str, raw_value: str
    ) -> WarningConfig:
        current = self.config(group_id).model_dump()
        current[key] = parse_field_value(WarningConfig, key, raw_value)
        validated = WarningConfig.model_validate(current)
        self._store.save_section(
            "warning",
            validated.model_dump(),
            group_id=group_id,
            defaults=WarningConfig().model_dump(),
        )
        return validated

    def reset_config(self, group_id: str, key: str | None = None) -> WarningConfig:
        if key and key not in WarningConfig.model_fields:
            raise ConfigError(f"Unknown config field: {key}")
        self._store.reset_section("warning", key, group_id=group_id)
        return self.config(group_id)

    def _window_and_threshold(self, group_id: str, category: str) -> tuple[int, int]:
        cfg = self.config(group_id)
        if category == "abuse":
            return cfg.abuse_window_seconds, cfg.abuse_threshold
        if category == "ad":
            return cfg.ad_window_seconds, cfg.ad_threshold
        return cfg.spam_window_seconds, cfg.spam_threshold

    def record_warning(
        self, group_id: str, member_id: str, category: str
    ) -> tuple[int, int]:
        """Record a warning and return (current_count, threshold)."""
        cfg = self.config(group_id)
        window, threshold = self._window_and_threshold(group_id, category)
        if not cfg.enabled:
            return 0, threshold
        now = time.monotonic()
        key = (group_id, member_id, category)
        timestamps = [t for t in self._warnings.get(key, []) if now - t <= window]
        timestamps.append(now)
        self._warnings[key] = timestamps
        return len(timestamps), threshold

    def clear_member(self, group_id: str, member_id: str) -> None:
        stale = [k for k in self._warnings if k[0] == group_id and k[1] == member_id]
        for key in stale:
            self._warnings.pop(key, None)

    def forget_group(self, group_id: str) -> None:
        for key in [k for k in self._warnings if k[0] == group_id]:
            self._warnings.pop(key, None)

    def clear(self) -> None:
        self._warnings.clear()


WARNING = WarningModule(CONFIG_STORE)

__all__ = ["WARNING", "WarningConfig", "WarningModule"]
