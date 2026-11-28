"""Mute duration normalization and compact human-readable formatting."""

from datetime import UTC, datetime, timedelta
import re
from typing import TypeAlias

MuteDuration: TypeAlias = int | float | str | timedelta | datetime

_DURATION_PATTERN = re.compile(r"^(\d+)([smhdSMHD]?)$")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_MUTE_SECONDS = 2_592_000


def parse_duration(duration: MuteDuration) -> int:
    """Convert seconds, shorthand ('10m', '2h', '1d'), timedelta, or datetime."""
    if isinstance(duration, datetime):
        now = datetime.now(UTC)
        target = duration if duration.tzinfo else duration.replace(tzinfo=UTC)
        seconds = int((target - now).total_seconds())
    elif isinstance(duration, timedelta):
        seconds = int(duration.total_seconds())
    elif isinstance(duration, (int, float)):
        seconds = int(duration)
    else:
        match = _DURATION_PATTERN.fullmatch(duration.strip())
        if not match:
            raise ValueError(
                f"Invalid mute duration {duration!r}; expected e.g. 600, '10m', '1h'."
            )
        seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]

    if not 1 <= seconds <= MAX_MUTE_SECONDS:
        raise ValueError(
            f"Mute duration must be between 1 and {MAX_MUTE_SECONDS} seconds."
        )
    return seconds


def format_duration(seconds: int) -> str:
    """Render seconds into compact units such as '10m', '2h', or '1d'."""
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


__all__ = ["MAX_MUTE_SECONDS", "MuteDuration", "format_duration", "parse_duration"]
