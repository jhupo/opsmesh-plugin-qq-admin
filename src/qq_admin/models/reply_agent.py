"""System 2 Agent 2: ReplyAgent for dynamic, persona-driven moderation replies."""

from dataclasses import dataclass, field
import json
import os
from typing import TYPE_CHECKING, Any

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    OutputGuardrailTripwireTriggered,
    Runner,
    SQLiteSession,
)
from openai import AsyncOpenAI

from qq_admin.config import AgentConfig, ConfigStore, SessionMode

from .guardrails import reply_guardrail

if TYPE_CHECKING:
    from qq_admin.manager import ServiceManager


@dataclass(slots=True)
class ReplySpec:
    """Live state snapshot and event facts supplied to ReplyAgent."""

    manager: "ServiceManager"
    group_id: str
    bot_role: str
    scenario: str
    actor_id: str = ""
    actor_role: str = "member"
    target_id: str = ""
    executed_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    fallback: str = ""


class ReplyAgent:
    """Encapsulates OpenAI Agents SDK reply composer with configurable sessions."""

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
        model_name = self.config.effective_reply_model
        if self.config.use_chat_completions:
            return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
        return OpenAIResponsesModel(model=model_name, openai_client=client)

    async def execute(
        self,
        spec: ReplySpec,
        *,
        session_key: str | None = None,
        session_mode: SessionMode | None = None,
    ) -> str:
        """Generate one natural, non-repetitive group admin reply."""
        if not self.is_ready:
            return spec.fallback

        sg_cfg = spec.manager.safeguard.config(spec.group_id)
        daily = spec.manager.safeguard.daily_counts(spec.group_id)
        catalog = spec.manager.catalog
        persona = self.config.reply_persona.strip() or catalog.composer_persona()
        instructions = catalog.composer_instructions(
            persona=persona,
            group_id=spec.group_id,
            bot_role=spec.bot_role,
            scenario=spec.scenario,
            actor_id=spec.actor_id or "unknown",
            actor_role=spec.actor_role,
            target_id=spec.target_id or "none",
            mute_count=daily["mute"],
            mute_limit=sg_cfg.daily_mute_limit,
            kick_count=daily["kick"],
            kick_limit=sg_cfg.daily_kick_limit,
        )

        agent = Agent[ReplySpec](
            name="QQGroupReplyAgent",
            instructions=instructions,
            model=self._build_model(),
            model_settings=ModelSettings(temperature=self.config.reply_temperature),
            output_guardrails=[reply_guardrail],
        )

        payload = {
            "scenario": spec.scenario,
            "executed_actions": spec.executed_actions,
            "facts": spec.facts,
        }
        mode = session_mode or self.session_mode(spec.group_id)
        session = (
            self._get_session(session_key or f"reply:{spec.group_id}")
            if mode == "shared"
            else None
        )

        try:
            result = await Runner.run(
                agent,
                input=json.dumps(payload, ensure_ascii=False),
                context=spec,
                max_turns=2,
                session=session,
            )
            text = str(result.final_output or "").strip()
            return text or spec.fallback
        except OutputGuardrailTripwireTriggered:
            return spec.fallback
        except Exception:
            return spec.fallback

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None


__all__ = ["ReplyAgent", "ReplySpec"]
