"""Thin TypeSafe AI Jev model runner exposing execute(inputs, outputs)."""

from collections.abc import Mapping

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Content,
    Image,
    Noul,
    Score,
    SystemOneResponse,
)

from qq_admin.config import Config

JevQuestion = Noul | Choice | Score

_IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}


class Jev:
    """Owns one AsyncTypeSafeClient and runs System One requests."""

    def __init__(
        self,
        config: Config,
        *,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None

    @property
    def is_ready(self) -> bool:
        return self._client is not None or bool(self.config.jev_api_key.strip())

    def _get_client(self) -> AsyncTypeSafeClient:
        if self._client is None:
            self._client = AsyncTypeSafeClient(
                api_key=self.config.jev_api_key.strip(),
                model=self.config.jev_model,
                timeout=self.config.timeout_seconds,
                headers=_IMAGE_HEADERS,
            )
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
            model=self.config.jev_model,
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


__all__ = ["AsyncTypeSafeClient", "Jev", "JevQuestion"]
