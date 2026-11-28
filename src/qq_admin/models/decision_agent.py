"""System 2 Agent 1: DecisionAgent for tool-calling moderation decisions."""

from dataclasses import dataclass, field
import os
from typing import TYPE_CHECKING, Any, Literal

from agents import (
    Agent,
    InputGuardrailTripwireTriggered,
    ModelSettings,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    Runner,
    SQLiteSession,
)
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from qq import Gateway

from qq_admin.config import AgentConfig, ConfigStore, SessionMode

from .guardrails import injection_guardrail
from .tools import GROUP_ADMIN_TOOLS

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager


@dataclass(slots=True)
class TurnContext:
    """Mutable per-turn context injected into DecisionAgent tools and guardrails."""

    gateway: Gateway
    manager: "ServiceManager"
    group_id: str
    member_id: str
    message_id: str
    message_text: str
    bot_role: str
    sender_role: str
    mode: Literal["auto_moderate", "admin_command"]
    jev_summary: str = ""
    executed_actions: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)


class DecisionOutcome(BaseModel):
    """Structured output returned by DecisionAgent for ReplyAgent consumption."""

    action_taken: bool = False
    should_reply: bool = False
    scenario: str = Field(
        default="moderation_action",
        description="Event scenario passed to ReplyAgent.",
    )
    target_member_id: str = ""
    executed_actions: list[str] = Field(default_factory=list)
    summary: str = ""


class DecisionAgent:
    """Encapsulates OpenAI Agents SDK decision runner with configurable sessions."""

    def __init__(
        self,
        config: AgentConfig,
        store: ConfigStore,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self._store = store
        self._client = client
        self._owns_client = client is None
        self._sessions: dict[str, SQLiteSession] = {}

    @property
    def is_ready(self) -> bool:
        if self._client is not None:
            return True
        return bool(self.config.secret_value or os.environ.get("OPENAI_API_KEY", ""))

    def session_mode(self, group_id: str | None = None) -> SessionMode:
        raw = self._store.load_section("agent", group_id=group_id)
        mode = raw.get("session_mode", self.config.session_mode)
        return "shared" if mode == "shared" else "fresh"

    def set_session_mode(
        self, mode: SessionMode, *, group_id: str | None = None
    ) -> SessionMode:
        raw = self._store.load_section("agent", group_id=group_id)
        raw["session_mode"] = mode
        self._store.save_section("agent", raw, group_id=group_id)
        if group_id is None:
            self.config = self.config.model_copy(update={"session_mode": mode})
        return mode

    def _get_session(self, session_key: str) -> SQLiteSession:
        session = self._sessions.get(session_key)
        if session is None:
            session = SQLiteSession(
                session_id=session_key,
                db_path=self.config.session_db_path,
            )
            self._sessions[session_key] = session
        return session

    async def reset_session(self, session_key: str) -> None:
        session = self._sessions.pop(session_key, None)
        if session is not None:
            await session.clear_session()

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            api_key = self.config.secret_value or os.environ.get("OPENAI_API_KEY", "")
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "timeout": self.config.timeout_seconds,
            }
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = AsyncOpenAI(**kwargs)
            self._owns_client = True
        return self._client

    def _build_model(self) -> OpenAIChatCompletionsModel | OpenAIResponsesModel:
        client = self._get_client()
        if self.config.use_chat_completions:
            return OpenAIChatCompletionsModel(
                model=self.config.decision_model,
                openai_client=client,
            )
        return OpenAIResponsesModel(
            model=self.config.decision_model,
            openai_client=client,
        )

    async def execute(
        self,
        prompt: str,
        *,
        context: TurnContext,
        session_key: str | None = None,
        session_mode: SessionMode | None = None,
    ) -> DecisionOutcome:
        """Execute one decision turn using fresh or shared session strategy."""
        catalog = context.manager.catalog
        role_policy = catalog.role_policy(context.bot_role)
        recent_ops = context.manager.audit.count_member_actions(
            context.group_id, context.member_id, within_hours=24.0
        )
        instructions = catalog.planner_prompt(
            context.mode,
            group_id=context.group_id,
            bot_role=context.bot_role,
            role_policy=role_policy,
            member_id=context.member_id,
            sender_role=context.sender_role,
            recent_ops=recent_ops,
            jev_summary=context.jev_summary,
        )

        agent = Agent[TurnContext](
            name="QQGroupDecisionAgent",
            instructions=instructions,
            model=self._build_model(),
            model_settings=ModelSettings(temperature=0.0),
            tools=GROUP_ADMIN_TOOLS,
            input_guardrails=[injection_guardrail],
            output_type=DecisionOutcome,
        )

        mode = session_mode or self.session_mode(context.group_id)
        session = (
            self._get_session(session_key or f"decision:{context.group_id}")
            if mode == "shared"
            else None
        )

        try:
            result = await Runner.run(
                agent,
                input=prompt,
                context=context,
                max_turns=self.config.max_turns,
                session=session,
            )
        except InputGuardrailTripwireTriggered:
            return DecisionOutcome(
                action_taken=False,
                should_reply=False,
                scenario="injection_blocked",
                target_member_id=context.member_id,
                summary="Blocked by Jev prompt-injection input guardrail.",
            )

        raw = result.final_output
        outcome = (
            raw
            if isinstance(raw, DecisionOutcome)
            else DecisionOutcome(
                action_taken=bool(context.executed_actions),
                should_reply=bool(context.executed_actions),
                target_member_id=context.member_id,
                summary=str(raw or ""),
            )
        )
        outcome.executed_actions = list(context.executed_actions)
        if context.executed_actions:
            outcome.action_taken = True
        if not outcome.target_member_id:
            outcome.target_member_id = context.member_id
        return outcome

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None


__all__ = ["DecisionAgent", "DecisionOutcome", "TurnContext"]
