"""Single flat plugin configuration for TypeSafe Jev and OpenAI Responses API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class Config(BaseModel):
    """Minimal startup configuration for Jev, ReplyAgent, and multi-group policy."""

    model_config = ConfigDict(extra="ignore")

    jev_api_key: str = ""
    jev_model: str = "jev-1"
    openai_api_key: str = ""
    openai_base_url: str = ""
    model: str = "gpt-5-mini"
    reasoning_effort: ReasoningEffort = "low"
    timeout_seconds: float = Field(default=30.0, gt=0)
    default_group_enabled: bool = False
    config_path: str = ""


__all__ = ["Config", "ReasoningEffort"]
