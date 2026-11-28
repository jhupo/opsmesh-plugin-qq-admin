"""Injectable async wrapper around typesafe_sdk.AsyncTypeSafeClient."""

import math
from typing import Any

from opsmesh.log import logger

from qq_admin.config import JevConfig


def import_typesafe_primitives() -> tuple[Any, Any, Any, Any, Any] | None:
    """Import typesafe_sdk classes lazily so the package degrades gracefully."""
    try:
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Image, Noul, Score
    except ImportError:
        return None
    return AsyncTypeSafeClient, Choice, Image, Noul, Score


class JevClient:
    """Explicit, injectable client wrapper for TypeSafe AI Jev system_one calls."""

    def __init__(
        self,
        config: JevConfig,
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self.config: JevConfig = config
        self._sdk_client: Any | None = sdk_client
        self._http_client: Any | None = None

    @property
    def is_ready(self) -> bool:
        return self.config.enabled and self._sdk_client is not None

    async def startup(self) -> None:
        """Create the underlying AsyncTypeSafeClient when not injected externally."""
        if self._sdk_client is not None or not self.config.enabled:
            return
        if not self.config.api_key.strip():
            logger.warning(
                "qq_admin Jev client has no api_key configured; running fail-open."
            )
            return
        primitives = import_typesafe_primitives()
        if primitives is None:
            logger.warning(
                "typesafe-sdk is not installed; Jev client running fail-open."
            )
            return
        AsyncTypeSafeClient = primitives[0]
        kwargs: dict[str, Any] = {
            "api_key": self.config.api_key,
            "timeout": self.config.timeout_seconds,
        }
        if self.config.proxy.strip():
            import httpx

            self._http_client = httpx.AsyncClient(
                proxy=self.config.proxy.strip(),
                timeout=self.config.timeout_seconds,
                headers={"TypeSafe-Danger-Zone-Images": "true"},
            )
            kwargs["http_client"] = self._http_client
        self._sdk_client = AsyncTypeSafeClient(**kwargs)
        logger.info(
            f"qq_admin TypeSafe Jev client initialized (model={self.config.model})."
        )

    async def shutdown(self) -> None:
        """Close the underlying SDK and HTTP clients cleanly."""
        if self._sdk_client is not None and hasattr(self._sdk_client, "aclose"):
            await self._sdk_client.aclose()
        self._sdk_client = None
        if self._http_client is not None and hasattr(self._http_client, "aclose"):
            await self._http_client.aclose()
        self._http_client = None

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        assets: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a raw TypeSafe Jev system_one call using configured model."""
        if not self.is_ready:
            raise RuntimeError("JevClient is not ready.")
        return await self._sdk_client.system_one(
            model=self.config.model,
            state=state,
            assets=assets,
            questions=questions,
        )

    async def evaluate_noul(
        self, instructions: str, state: dict[str, Any]
    ) -> float | None:
        """Evaluate a single calibrated probability question (0.0..1.0)."""
        if not self.is_ready:
            return None
        primitives = import_typesafe_primitives()
        Noul = primitives[3] if primitives is not None else None
        q = (
            Noul(instructions=instructions)
            if Noul is not None
            else {"noul": instructions}
        )
        try:
            resp = await self.system_one(state=state, questions={"matches": q})
            val = float(resp.answers["matches"].noul)
            return val if math.isfinite(val) and 0.0 <= val <= 1.0 else None
        except Exception as exc:
            logger.warning(f"qq_admin Jev noul evaluation failed: {exc}")
            return None


__all__ = ["JevClient", "import_typesafe_primitives"]
