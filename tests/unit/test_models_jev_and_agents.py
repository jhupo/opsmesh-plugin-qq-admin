"""Tests for Jev.execute, stateless ReplyAgent, and deterministic reply_guardrail."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from agents import RunContextWrapper, Runner
import pytest

from qq_admin import (
    MANAGER,
    MODERATION,
    Config,
    ReplySpec,
    reply_guardrail,
    sanitize_reply_text,
)


def _mock_jev_resp(
    *,
    nouls: dict[str, float] | None = None,
    scores: dict[str, tuple[float, float]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=v) for k, v in (nouls or {}).items()},
        scores={
            k: SimpleNamespace(score=s, confidence=conf)
            for k, (s, conf) in (scores or {}).items()
        },
    )


@pytest.mark.anyio
async def test_jev_execute_text_image_and_url_inputs() -> None:
    fake_client = MagicMock()
    fake_client.system_one = AsyncMock(
        return_value=_mock_jev_resp(
            nouls={
                "violence": 0.02,
                "sexual_content": 0.01,
                "advertising": 0.94,
                "prompt_injection": 0.05,
            },
            scores={"severity": (3.0, 0.92)},
        )
    )
    fake_client.aclose = AsyncMock()

    MANAGER.setup(Config(jev_model="jev-1"), jev_client=fake_client)

    report = await MANAGER.jev.execute(
        text="buy cheap promo",
        images=[b"fake-png-bytes"],
        urls=["https://example.com/promo"],
    )
    assert report.advertising == 0.94
    assert report.severity == 3
    assert report.primary_category == "advertising"
    assert report.is_flagged(0.70)
    assert "advertising" in report.triggered(0.70)

    # Image-only call automatically skips text-only attack questions
    img_only = await MANAGER.jev.execute(images=[b"fake-png-bytes"])
    assert img_only.is_flagged(0.70)
    last_questions = fake_client.system_one.await_args.kwargs["questions"]
    assert "prompt_injection" not in last_questions
    assert "jailbreak" not in last_questions

    url_only = await MANAGER.jev.execute(urls=["https://example.com/ad"])
    assert url_only.is_flagged(0.70)

    fake_client.system_one = AsyncMock(
        return_value=_mock_jev_resp(
            nouls={"violence": 0.01, "advertising": 0.02},
            scores={"severity": (0.0, 0.99)},
        )
    )
    safe = await MANAGER.jev.execute(text="hello everyone")
    assert not safe.is_flagged(0.70)


@pytest.mark.anyio
async def test_stateless_reply_agent_and_pure_code_guardrail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_jev = MagicMock()
    fake_jev.system_one = AsyncMock()
    fake_openai = MagicMock()
    fake_openai.close = AsyncMock()

    MANAGER.setup(
        Config(model="gpt-5-mini", reasoning_effort="low"),
        jev_client=fake_jev,
        openai_client=fake_openai,
    )
    MODERATION.update_config("G1", "group_rule_hint", "Rust discussion only")

    captured_agents: list[object] = []

    async def _fake_run(agent, input, **kwargs):
        del input, kwargs
        captured_agents.append(agent)
        return SimpleNamespace(final_output='"Muted U1 for 10m due to spam."')

    monkeypatch.setattr(Runner, "run", _fake_run)

    reply = await MANAGER.reply_agent.execute(
        ReplySpec(
            group_id="G1",
            bot_role="admin",
            scenario="auto_moderation",
            target_id="U1",
            categories=["advertising"],
            executed_actions=["mute"],
            fallback="fallback",
        )
    )
    assert reply == "Muted U1 for 10m due to spam."
    assert captured_agents[-1].model_settings.reasoning.effort == "low"
    assert "Rust discussion only" in captured_agents[-1].instructions

    assert sanitize_reply_text("```text\nHello\n```") == "Hello"

    # Output guardrail runs in 0ms pure code with zero Jev network calls
    empty_spec = ReplySpec(
        group_id="G1",
        bot_role="admin",
        scenario="auto_moderation",
        executed_actions=[],
    )
    safe_out = await reply_guardrail.guardrail_function(
        RunContextWrapper(empty_spec), MagicMock(), "Noted, please watch the rules."
    )
    assert safe_out.tripwire_triggered is False

    # Oversized reply triggers pure-code tripwire
    long_out = await reply_guardrail.guardrail_function(
        RunContextWrapper(empty_spec), MagicMock(), "x" * 250
    )
    assert long_out.tripwire_triggered is True
    fake_jev.system_one.assert_not_awaited()
