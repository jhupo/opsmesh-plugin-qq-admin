"""Shared context and structured handoff models for DecisionPlanner & ReplyComposer."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.jev import MessageAssessment

if TYPE_CHECKING:
    from qq_admin.runtime import AdminRuntime


class DecisionOutcome(BaseModel):
    """Structured output emitted by DecisionPlanner for ReplyComposer."""

    action_taken: bool = False
    should_reply: bool = False
    scenario: Literal[
        "violation_handled",
        "guard_blocked",
        "admin_command",
        "no_action",
    ] = "no_action"
    target_id: str = ""
    executed_actions: list[str] = Field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class TurnContext:
    """Per-turn execution context passed to DecisionPlanner and its tools."""

    gateway: Gateway
    runtime: "AdminRuntime"
    group_id: str
    member_id: str
    message_id: str
    text: str
    bot_role: str
    sender_role: str
    mode: Literal["auto_moderate", "admin_command"]
    assessment: MessageAssessment | None = None
    executed_actions: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReplySpec:
    """State and event facts passed to ReplyComposer for natural phrasing."""

    runtime: "AdminRuntime"
    group_id: str
    bot_role: str
    scenario: str
    actor_id: str
    actor_role: str
    target_id: str = ""
    executed_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    fallback: str = ""


__all__ = ["DecisionOutcome", "ReplySpec", "TurnContext"]
