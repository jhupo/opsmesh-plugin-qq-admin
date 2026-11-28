"""Single flat plugin configuration for TypeSafe Jev and OpenAI Responses API."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class Config(BaseModel):
    """Minimal startup configuration for Jev and both OpenAI Responses agents."""

    model_config = ConfigDict(extra="ignore")

    jev_api_key: SecretStr = Field(default=SecretStr(""))
    jev_model: str = Field(default="jev-1")
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_base_url: str = Field(default="")
    model: str = Field(default="gpt-5-mini")
    reasoning_effort: ReasoningEffort | None = Field(default="low")
    timeout_seconds: float = Field(default=30.0, gt=0)
    config_path: str = Field(default="")
    prompts_path: str = Field(default="")

    @property
    def effective_jev_key(self) -> str:
        return (
            self.jev_api_key.get_secret_value().strip()
            or os.environ.get("TYPESAFE_API_KEY", "").strip()
        )

    @property
    def effective_openai_key(self) -> str:
        return (
            self.openai_api_key.get_secret_value().strip()
            or os.environ.get("OPENAI_API_KEY", "").strip()
        )


__all__ = ["Config", "ReasoningEffort"]
