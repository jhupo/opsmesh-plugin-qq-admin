"""Calibrated Jev evaluators and guardrail checks accepting an explicit JevClient."""

from typing import Any

from opsmesh.log import logger

from .client import JevClient, import_typesafe_primitives
from .schemas import (
    GuardVerdict,
    ImageViolationType,
    JoinRiskEvaluation,
    MessageEvaluation,
)


async def evaluate_message(
    jev: JevClient,
    prompts: dict[str, Any],
    *,
    text: str,
    group_openid: str,
    member_openid: str,
    recent_messages: list[dict[str, str]] | None = None,
    image_bytes_list: list[bytes] | None = None,
) -> MessageEvaluation:
    """Run one parallel Jev system_one evaluation over message text and images."""
    if not jev.is_ready:
        return MessageEvaluation(status="unavailable")

    primitives = import_typesafe_primitives()
    if primitives is not None:
        _, Choice, Image, Noul, Score = primitives
    else:
        Choice = Image = Noul = Score = None

    cfg = jev.config
    ts_cfg = prompts.get("jev", {}).get("incoming", {})

    assets: dict[str, Any] = {}
    if cfg.enable_image_review and image_bytes_list:
        for idx, raw in enumerate(image_bytes_list[: cfg.max_images], start=1):
            assets[f"img_{idx}"] = Image(raw) if Image is not None else raw

    state: dict[str, Any] = {
        "group_openid": group_openid,
        "member_openid": member_openid,
        "text": text[:2000],
        "recent_messages": recent_messages or [],
    }
    if assets:
        state["attached_images"] = list(assets.keys())

    def _noul(inst: str) -> Any:
        return Noul(instructions=inst) if Noul is not None else {"noul": inst}

    def _choice(inst: str, crit: dict[str, str]) -> Any:
        if Choice is not None:
            return Choice(instructions=inst, criteria=crit)
        return {"choice": inst, "criteria": crit}

    def _score(inst: str, crit: dict[str, str]) -> Any:
        if Score is not None:
            return Score(instructions=inst, criteria=crit)
        return {"score": inst, "criteria": crit}

    questions: dict[str, Any] = {
        "is_prompt_injection": _noul(ts_cfg.get("is_prompt_injection", "")),
        "text_violation_type": _choice(
            ts_cfg.get("text_violation_instructions", ""),
            ts_cfg.get("text_violation_criteria", {}),
        ),
        "is_friendly_banter": _noul(ts_cfg.get("is_friendly_banter", "")),
        "violation_severity": _score(
            ts_cfg.get("violation_severity_instructions", ""),
            ts_cfg.get("violation_severity_criteria", {}),
        ),
    }
    if assets:
        questions["image_violation_type"] = _choice(
            ts_cfg.get("image_violation_instructions", ""),
            ts_cfg.get("image_violation_criteria", {}),
        )

    try:
        resp = await jev.system_one(
            state=state,
            assets=assets or None,
            questions=questions,
        )
        ans = resp.answers
        img_type: ImageViolationType = "none"
        img_conf = 0.0
        if assets and "image_violation_type" in ans:
            iv = ans["image_violation_type"]
            img_type = iv.choice
            img_conf = float(iv.confidence)
        return MessageEvaluation(
            status="ok",
            is_prompt_injection_prob=float(ans["is_prompt_injection"].noul),
            text_violation_type=ans["text_violation_type"].choice,
            text_violation_confidence=float(ans["text_violation_type"].confidence),
            image_violation_type=img_type,
            image_violation_confidence=img_conf,
            is_friendly_banter_prob=float(ans["is_friendly_banter"].noul),
            violation_severity=float(ans["violation_severity"].score),
            severity_confidence=float(ans["violation_severity"].confidence),
        )
    except Exception as exc:
        logger.warning(f"qq_admin Jev evaluate_message failed: {exc}")
        return MessageEvaluation(status="unavailable")


async def evaluate_join_request(
    jev: JevClient,
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
    prob = await jev.evaluate_noul(
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
    jev: JevClient, prompts: dict[str, Any], text: str
) -> GuardVerdict:
    """Check whether input text attempts prompt injection."""
    inst = prompts.get("jev", {}).get("guards", {}).get("input_injection", "")
    prob = await jev.evaluate_noul(inst, {"input": text[:2000]})
    if prob is None:
        return GuardVerdict(blocked=False, probability=0.0)
    blocked = prob >= jev.config.injection_block_threshold
    return GuardVerdict(
        blocked=blocked,
        probability=prob,
        reason="Prompt injection detected." if blocked else "",
    )


async def check_action_validity(
    jev: JevClient,
    prompts: dict[str, Any],
    *,
    proposal: dict[str, Any],
    evidence: dict[str, Any],
) -> GuardVerdict:
    """Verify whether evidence justifies the proposed moderation tool call."""
    if not jev.config.enable_action_guardrail or not jev.is_ready:
        return GuardVerdict(blocked=False, probability=1.0)
    inst = prompts.get("jev", {}).get("guards", {}).get("moderation_validity", "")
    prob = await jev.evaluate_noul(inst, {"proposal": proposal, "evidence": evidence})
    if prob is None:
        return GuardVerdict(
            blocked=True,
            probability=0.0,
            reason="Jev action verification unavailable.",
        )
    blocked = prob < jev.config.action_validity_threshold
    return GuardVerdict(
        blocked=blocked,
        probability=prob,
        reason="Insufficient evidence for proposed action." if blocked else "",
    )


async def check_output_safety(
    jev: JevClient, prompts: dict[str, Any], text: str
) -> GuardVerdict:
    """Verify that a generated moderation reply is safe and on-topic."""
    inst = prompts.get("jev", {}).get("guards", {}).get("output_safety", "")
    prob = await jev.evaluate_noul(inst, {"output": text[:1000]})
    if prob is None:
        return GuardVerdict(blocked=False, probability=0.0)
    blocked = prob >= jev.config.output_safety_threshold
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
