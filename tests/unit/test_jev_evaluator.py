"""Unit tests for JevEvaluator with official typesafe-sdk primitives."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    ChoiceAnswer,
    Image,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
)

from qq_admin import JevEvaluator, JevSettings, PromptCatalog


def _sys1_response(
    *,
    nouls: dict[str, NoulAnswer] | None = None,
    choices: dict[str, ChoiceAnswer] | None = None,
    scores: dict[str, ScoreAnswer] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        nouls=nouls or {},
        choices=choices or {},
        scores=scores or {},
    )


@pytest.mark.anyio
async def test_jev_evaluator_multimodal_banter_and_guard_checks() -> None:
    catalog = PromptCatalog.load()
    client = AsyncMock(spec=AsyncTypeSafeClient)
    settings = JevSettings(enabled=True, model="jev-1")
    jev = JevEvaluator(settings, catalog, client=client)

    client.system_one.return_value = _sys1_response(
        nouls={
            "is_prompt_injection": NoulAnswer(type="noul", noul=0.03),
            "is_friendly_banter": NoulAnswer(type="noul", noul=0.01),
        },
        choices={
            "text_violation_type": ChoiceAnswer(
                type="choice", choice="none", confidence=0.92, probabilities={}
            ),
            "image_violation_type": ChoiceAnswer(
                type="choice", choice="qr_ad_promo", confidence=0.95, probabilities={}
            ),
        },
        scores={
            "violation_severity": ScoreAnswer(
                type="score", score=3.6, confidence=0.93, legend={}, probabilities={}
            )
        },
    )
    assessment = await jev.assess_message(
        "G1", "U1", "scan QR", images=[b"\x89PNGfake"]
    )
    assert assessment.primary_violation == "image:qr_ad_promo"
    assert assessment.warning_category == "ad"
    assert assessment.enforcement_tier(settings) == "severe"

    call_kwargs = client.system_one.await_args.kwargs
    assert isinstance(call_kwargs["questions"]["is_prompt_injection"], Noul)
    assert isinstance(call_kwargs["questions"]["text_violation_type"], Choice)
    assert isinstance(call_kwargs["questions"]["violation_severity"], Score)
    assert isinstance(call_kwargs["assets"]["img_1"], Image)

    client.system_one.return_value = _sys1_response(
        nouls={
            "is_prompt_injection": NoulAnswer(type="noul", noul=0.01),
            "is_friendly_banter": NoulAnswer(type="noul", noul=0.88),
        },
        choices={
            "text_violation_type": ChoiceAnswer(
                type="choice",
                choice="harassment_abuse",
                confidence=0.89,
                probabilities={},
            )
        },
        scores={
            "violation_severity": ScoreAnswer(
                type="score", score=2.1, confidence=0.90, legend={}, probabilities={}
            )
        },
    )
    banter = await jev.assess_message("G1", "U2", "friendly joke")
    assert banter.enforcement_tier(settings) == "none"

    client.system_one.return_value = _sys1_response(
        nouls={"matches": NoulAnswer(type="noul", noul=0.94)}
    )
    assert (await jev.check_injection("ignore instructions")).blocked is True

    client.system_one.return_value = _sys1_response(
        nouls={"matches": NoulAnswer(type="noul", noul=0.25)}
    )
    assert (
        await jev.verify_action(
            proposal={"tool": "kick_member", "arguments": {"member_id": "U1"}},
            evidence={"message_text": "hi"},
        )
    ).blocked is True

    client.system_one.return_value = _sys1_response(
        nouls={"matches": NoulAnswer(type="noul", noul=0.89)}
    )
    assert (await jev.check_reply("unsafe text")).blocked is True

    client.system_one.return_value = _sys1_response(
        nouls={"matches": NoulAnswer(type="noul", noul=0.91)}
    )
    join_eval = await jev.assess_join_request("promo", [])
    assert join_eval.risk_probability == pytest.approx(0.91)
