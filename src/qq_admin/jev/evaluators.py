"""Calibrated evaluators calling official typesafe_sdk.AsyncTypeSafeClient directly."""

import math
from typing import Any, cast

from opsmesh.log import logger
from typesafe_sdk import AsyncTypeSafeClient, Choice, Image, Noul, Score

from qq_admin.config import JevConfig

from .schemas import (
    GuardVerdict,
    ImageViolationType,
    JoinRiskEvaluation,
    MessageEvaluation,
    TextViolationType,
)


async def evaluate_message(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    prompts: dict[str, Any],
    *,
    text: str,
    group_openid: str,
    member_openid: str,
    recent_messages: list[dict[str, str]] | None = None,
    image_bytes_list: list[bytes] | None = None,
) -> MessageEvaluation:
    """Run one parallel system_one call directly on AsyncTypeSafeClient."""
    if client is None or not config.enabled:
        return MessageEvaluation(status="unavailable")

    ts_cfg = prompts.get("jev", {}).get("incoming", {})
    assets: dict[str, Image] = {}
    if config.enable_image_review and image_bytes_list:
        for idx, raw in enumerate(image_bytes_list[: config.max_images], start=1):
            assets[f"img_{idx}"] = Image(raw)

    state: dict[str, Any] = {
        "group_openid": group_openid,
        "member_openid": member_openid,
        "text": text[:2000],
        "recent_messages": recent_messages or [],
    }
    if assets:
        state["attached_images"] = list(assets.keys())

    questions: dict[str, Noul | Choice | Score] = {
        "is_prompt_injection": Noul(instructions=ts_cfg.get("is_prompt_injection", "")),
        "text_violation_type": Choice(
            instructions=ts_cfg.get("text_violation_instructions", ""),
            criteria=ts_cfg.get("text_violation_criteria", {}),
        ),
        "is_friendly_banter": Noul(instructions=ts_cfg.get("is_friendly_banter", "")),
        "violation_severity": Score(
            instructions=ts_cfg.get("violation_severity_instructions", ""),
            criteria=list(ts_cfg.get("violation_severity_criteria", [])),
        ),
    }
    if assets:
        questions["image_violation_type"] = Choice(
            instructions=ts_cfg.get("image_violation_instructions", ""),
            criteria=ts_cfg.get("image_violation_criteria", {}),
        )

    try:
        resp = await client.system_one(
            state=state,
            questions=questions,
            model=config.model,
            assets=assets or None,
        )
        inj = resp.nouls["is_prompt_injection"]
        banter = resp.nouls["is_friendly_banter"]
        tv = resp.choices["text_violation_type"]
        vsev = resp.scores["violation_severity"]

        img_type: ImageViolationType = "none"
        img_conf = 0.0
        if assets and "image_violation_type" in resp.choices:
            iv = resp.choices["image_violation_type"]
            img_type = cast(ImageViolationType, iv.choice)
            img_conf = float(iv.confidence)

        return MessageEvaluation(
            status="ok",
            is_prompt_injection_prob=float(inj.noul),
            text_violation_type=cast(TextViolationType, tv.choice),
            text_violation_confidence=float(tv.confidence),
            image_violation_type=img_type,
            image_violation_confidence=img_conf,
            is_friendly_banter_prob=float(banter.noul),
            violation_severity=float(vsev.score),
            severity_confidence=float(vsev.confidence),
        )
    except Exception as exc:
        logger.warning(f"qq_admin TypeSafe evaluate_message failed: {exc}")
        return MessageEvaluation(status="unavailable")


async def _evaluate_noul(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    instructions: str,
    state: dict[str, Any],
) -> float | None:
    if client is None or not config.enabled:
        return None
    try:
        resp = await client.system_one(
            state=state,
            questions={"matches": Noul(instructions=instructions)},
            model=config.model,
        )
        val = float(resp.nouls["matches"].noul)
        return val if math.isfinite(val) and 0.0 <= val <= 1.0 else None
    except Exception as exc:
        logger.warning(f"qq_admin TypeSafe noul check failed: {exc}")
        return None


async def evaluate_join_request(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    prompts: dict[str, Any],
    *,
    verify_message: str,
    qa_pairs: list[dict[str, str]],
    risk_tips: str | None,
) -> JoinRiskEvaluation:
    """Score whether a join request is high-risk spam or malicious."""
    inst = (
        prompts.get("jev", {}).get("join_request", {}).get("is_risky_instructions", "")
    )
    prob = await _evaluate_noul(
        client,
        config,
        inst,
        {
            "verify_message": verify_message,
            "qa_pairs": qa_pairs,
            "risk_tips": risk_tips or "",
        },
    )
    if prob is None:
        return JoinRiskEvaluation(status="unavailable")
    return JoinRiskEvaluation(status="ok", risk_probability=prob)


async def check_input_injection(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    prompts: dict[str, Any],
    text: str,
) -> GuardVerdict:
    """Check whether input text attempts prompt injection."""
    inst = prompts.get("jev", {}).get("guards", {}).get("input_injection", "")
    prob = await _evaluate_noul(client, config, inst, {"input": text[:2000]})
    if prob is None:
        return GuardVerdict(blocked=False, probability=0.0)
    blocked = prob >= config.injection_block_threshold
    return GuardVerdict(
        blocked=blocked,
        probability=prob,
        reason="Prompt injection detected." if blocked else "",
    )


async def check_action_validity(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    prompts: dict[str, Any],
    *,
    proposal: dict[str, Any],
    evidence: dict[str, Any],
) -> GuardVerdict:
    """Verify whether evidence justifies the proposed moderation tool call."""
    if not config.enable_action_guardrail or client is None or not config.enabled:
        return GuardVerdict(blocked=False, probability=1.0)
    inst = prompts.get("jev", {}).get("guards", {}).get("moderation_validity", "")
    prob = await _evaluate_noul(
        client, config, inst, {"proposal": proposal, "evidence": evidence}
    )
    if prob is None:
        return GuardVerdict(
            blocked=True,
            probability=0.0,
            reason="TypeSafe action verification unavailable.",
        )
    blocked = prob < config.action_validity_threshold
    return GuardVerdict(
        blocked=blocked,
        probability=prob,
        reason="Insufficient evidence for proposed action." if blocked else "",
    )


async def check_output_safety(
    client: AsyncTypeSafeClient | None,
    config: JevConfig,
    prompts: dict[str, Any],
    text: str,
) -> GuardVerdict:
    """Verify that a generated moderation reply is safe and on-topic."""
    inst = prompts.get("jev", {}).get("guards", {}).get("output_safety", "")
    prob = await _evaluate_noul(client, config, inst, {"output": text[:1000]})
    if prob is None:
        return GuardVerdict(blocked=False, probability=0.0)
    blocked = prob >= config.output_safety_threshold
    return GuardVerdict(
        blocked=blocked,
        probability=prob,
        reason="Unsafe moderation notice blocked." if blocked else "",
    )


__all__ = [
    "check_action_validity",
    "check_input_injection",
    "check_output_safety",
    "evaluate_join_request",
    "evaluate_message",
]
