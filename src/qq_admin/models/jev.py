"""Thin TypeSafe AI Jev model runner exposing execute(inputs, outputs)."""

from collections.abc import Mapping
import os
from typing import Any

import httpx2
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Content,
    Image,
    Noul,
    Score,
    SystemOneResponse,
)

from qq_admin.config import JevConfig

JevQuestion = Noul | Choice | Score

_IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}


class Jev:
    """Owns one AsyncTypeSafeClient and runs System One requests."""

    def __init__(
        self,
        config: JevConfig,
        *,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None
        self._http_client: httpx2.AsyncClient | None = None

    @property
    def api_key(self) -> str:
        return (
            self.config.secret_value or os.environ.get("TYPESAFE_API_KEY", "").strip()
        )

    @property
    def is_ready(self) -> bool:
        return self._client is not None or bool(self.api_key)

    def _get_client(self) -> AsyncTypeSafeClient:
        if self._client is not None:
            return self._client
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "model": self.config.model,
            "timeout": self.config.timeout_seconds,
            "headers": _IMAGE_HEADERS,
        }
        if self.config.proxy.strip():
            self._http_client = httpx2.AsyncClient(
                proxy=self.config.proxy.strip(),
                http2=True,
                timeout=self.config.timeout_seconds,
                headers=_IMAGE_HEADERS,
            )
            kwargs["http_client"] = self._http_client
        self._client = AsyncTypeSafeClient(**kwargs)
        self._owns_client = True
        return self._client

    async def execute(
        self,
        inputs: Content,
        outputs: Mapping[str, JevQuestion],
        *,
        images: Mapping[str, Image] | None = None,
    ) -> SystemOneResponse:
        """Evaluate structured inputs against the requested output questions."""
        return await self._get_client().system_one(
            state=inputs,
            questions=outputs,
            model=self.config.model,
            assets=images or None,
        )

    async def probability(self, inputs: Content, instructions: str) -> float:
        """Shortcut for a single Noul question; returns the probability."""
        resp = await self.execute(inputs, {"answer": Noul(instructions=instructions)})
        return float(resp.nouls["answer"].noul)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


__all__ = ["AsyncTypeSafeClient", "Jev", "JevQuestion"]
