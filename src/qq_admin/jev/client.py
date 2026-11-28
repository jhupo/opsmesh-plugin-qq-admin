"""Factory and lifecycle helpers for official typesafe_sdk.AsyncTypeSafeClient."""

import os
from typing import Any

from opsmesh.log import logger
from typesafe_sdk import AsyncTypeSafeClient

from qq_admin.config import JevConfig

_IMAGE_DANGER_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}


def create_jev_client(
    config: JevConfig,
) -> tuple[AsyncTypeSafeClient | None, Any | None]:
    """Create a real AsyncTypeSafeClient from JevConfig (with optional httpx2 proxy)."""
    if not config.enabled:
        return None, None
    api_key = config.api_key.strip() or os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "qq_admin Jev enabled without api_key / TYPESAFE_API_KEY; fail-open."
        )
        return None, None

    http_client: Any | None = None
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": config.model,
        "timeout": config.timeout_seconds,
        "headers": _IMAGE_DANGER_HEADERS,
    }
    if config.proxy.strip():
        import httpx2

        http_client = httpx2.AsyncClient(
            proxy=config.proxy.strip(),
            http2=True,
            timeout=config.timeout_seconds,
            headers=_IMAGE_DANGER_HEADERS,
        )
        kwargs["http_client"] = http_client

    client = AsyncTypeSafeClient(**kwargs)
    logger.info(f"qq_admin AsyncTypeSafeClient initialized (model={config.model}).")
    return client, http_client


async def close_jev_client(
    client: AsyncTypeSafeClient | None,
    http_client: Any | None = None,
) -> None:
    """Close AsyncTypeSafeClient and optional httpx2.AsyncClient."""
    if client is not None:
        await client.aclose()
    if http_client is not None and hasattr(http_client, "aclose"):
        await http_client.aclose()


__all__ = ["AsyncTypeSafeClient", "close_jev_client", "create_jev_client"]
