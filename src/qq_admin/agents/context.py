"""Shared contexts and structured handoff models for the dual-agent pipeline."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.jev import MessageEvaluation
from qq_admin.state import PluginRuntime


class ExecutionReport(BaseModel):
    """Structured output of DecisionAgent handed to ReplyAgent."""

    action_taken: bool = False
    should_reply: bool = False
    scenario: Literal[
        "violation_handled",
        "guard_blocked",
        "admin_command",
        "no_action",
    ] = "no_action"
    target_openid: str = ""
    executed_actions: list[str] = Field(default_factory=list)
    facts_summary: str = ""


@dataclass(slots=True)
class ModerationContext:
    """Per-turn execution context passed through DecisionAgent."""

    gateway: Gateway
    runtime: PluginRuntime
    group_openid: str
    member_openid: str
    message_id: str
    plain_text: str
    bot_role: str
    sender_role: str
    mode: Literal["auto_moderate", "admin_command"]
    evaluation: MessageEvaluation | None = None
    executed_actions: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReplyContext:
    """Live state + outcome context passed to ReplyAgent for natural phrasing."""

    runtime: PluginRuntime
    group_openid: str
    bot_role: str
    scenario: str
    actor_openid: str
    actor_role: str
    target_openid: str = ""
    executed_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    fallback_text: str = ""


__all__ = ["ExecutionReport", "ModerationContext", "ReplyContext"]
