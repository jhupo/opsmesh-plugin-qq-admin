"""Human-readable mute duration parsing and formatting (Official QQ v2 limits)."""

from dataclasses import dataclass
import re

MAX_QQ_MUTE_SECONDS = 2_592_000  # 30 days
MIN_QQ_MUTE_SECONDS = 1

_DURATION_RE = re.compile(
    r"^\s*(?P<value>\d+)\s*(?P<unit>s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)?\s*$",
    re.IGNORECASE,
)

_UNIT_MULTIPLIERS: dict[str, int] = {
    "": 60,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}


@dataclass(frozen=True, slots=True)
class MuteDuration:
    """Validated mute duration clamped to Official QQ v2 bounds."""

    seconds: int

    @property
    def label(self) -> str:
        return format_duration(self.seconds)


def parse_duration(raw: int | str) -> MuteDuration | None:
    """Parse an int (seconds) or string such as '10m', '2h', '300s', '1d'."""
    if isinstance(raw, int):
        if raw < MIN_QQ_MUTE_SECONDS:
            return None
        return MuteDuration(seconds=min(raw, MAX_QQ_MUTE_SECONDS))

    text = str(raw).strip()
    if not text:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        return None
    value = int(match.group("value"))
    unit = (match.group("unit") or "").lower()
    seconds = value * _UNIT_MULTIPLIERS.get(unit, 60)
    if seconds < MIN_QQ_MUTE_SECONDS:
        return None
    return MuteDuration(seconds=min(seconds, MAX_QQ_MUTE_SECONDS))


def format_duration(seconds: int) -> str:
    """Format a duration in seconds into compact human-readable form."""
    if seconds % 86400 == 0 and seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0 and seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


__all__ = [
    "MAX_QQ_MUTE_SECONDS",
    "MIN_QQ_MUTE_SECONDS",
    "MuteDuration",
    "format_duration",
    "parse_duration",
]
