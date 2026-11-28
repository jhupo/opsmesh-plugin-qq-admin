"""JevEvaluator driven by an injected official typesafe_sdk.AsyncTypeSafeClient."""

import math
import os
from typing import Any, cast

from opsmesh.log import logger
from typesafe_sdk import AsyncTypeSafeClient, Choice, Image, Noul, Score

from qq_admin.config import JevSettings
from qq_admin.resources import PromptCatalog

from .schemas import (
    ImageViolationType,
    JoinRiskAssessment,
    MessageAssessment,
    SafetyVerdict,
    TextViolationType,
)

_IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}


class JevEvaluator:
    """Cohesive System 1 evaluator wrapping an injected AsyncTypeSafeClient."""

    def __init__(
        self,
        settings: JevSettings,
        catalog: PromptCatalog,
        *,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.client: AsyncTypeSafeClient | None = client
        self._owns_client = False
        self._http_client: Any | None = None

    @property
    def is_active(self) -> bool:
        return self.settings.enabled and self.client is not None

    def attach_client(self, client: AsyncTypeSafeClient | None) -> None:
        """Bind an externally managed AsyncTypeSafeClient instance."""
        self.client = client
        self._owns_client = False

    async def open(self) -> None:
        """Create an owned AsyncTypeSafeClient when none was injected."""
        if self.client is not None or not self.settings.enabled:
            return
        api_key = (
            self.settings.secret_value or os.environ.get("TYPESAFE_API_KEY", "").strip()
        )
        if not api_key:
            logger.warning(
                "qq_admin Jev enabled without api_key / TYPESAFE_API_KEY; fail-open."
            )
            return

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": self.settings.model,
            "timeout": self.settings.timeout_seconds,
            "headers": _IMAGE_HEADERS,
        }
        if self.settings.proxy.strip():
            import httpx2

            self._http_client = httpx2.AsyncClient(
                proxy=self.settings.proxy.strip(),
                http2=True,
                timeout=self.settings.timeout_seconds,
                headers=_IMAGE_HEADERS,
            )
            kwargs["http_client"] = self._http_client

        self.client = AsyncTypeSafeClient(**kwargs)
        self._owns_client = True
        logger.info(
            f"qq_admin AsyncTypeSafeClient ready (model={self.settings.model})."
        )

    async def close(self) -> None:
        """Close owned AsyncTypeSafeClient and proxy transport cleanly."""
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None
            self._owns_client = False
        if self._http_client is not None and hasattr(self._http_client, "aclose"):
            await self._http_client.aclose()
            self._http_client = None

    async def assess_message(
        self,
        group_id: str,
        member_id: str,
        text: str,
        *,
        recent_messages: list[dict[str, str]] | None = None,
        images: list[bytes] | None = None,
    ) -> MessageAssessment:
        """Assess text and optional image attachments in one parallel Jev call."""
        if not self.is_active or self.client is None:
            return MessageAssessment(status="unavailable")

        cfg = self.catalog.jev.get("incoming", {})
        assets = self._prepare_images(images)
        state: dict[str, Any] = {
            "group_id": group_id,
            "member_id": member_id,
            "text": text[:2000],
            "recent_messages": recent_messages or [],
        }
        if assets:
            state["attached_images"] = list(assets.keys())

        questions = self._build_message_questions(cfg, has_images=bool(assets))
        try:
            resp = await self.client.system_one(
                state=state,
                questions=questions,
                model=self.settings.model,
                assets=assets or None,
            )
            return self._parse_message_response(resp, has_images=bool(assets))
        except Exception as exc:
            logger.warning(f"qq_admin Jev assess_message failed: {exc}")
            return MessageAssessment(status="unavailable")

    def _prepare_images(self, images: list[bytes] | None) -> dict[str, Image]:
        if not self.settings.enable_image_review or not images:
            return {}
        return {
            f"img_{idx}": Image(raw)
            for idx, raw in enumerate(images[: self.settings.max_images], start=1)
        }

    @staticmethod
    def _build_message_questions(
        cfg: dict[str, Any], *, has_images: bool
    ) -> dict[str, Noul | Choice | Score]:
        questions: dict[str, Noul | Choice | Score] = {
            "is_prompt_injection": Noul(
                instructions=cfg.get("is_prompt_injection", "")
            ),
            "text_violation_type": Choice(
                instructions=cfg.get("text_violation_instructions", ""),
                criteria=cfg.get("text_violation_criteria", {}),
            ),
            "is_friendly_banter": Noul(instructions=cfg.get("is_friendly_banter", "")),
            "violation_severity": Score(
                instructions=cfg.get("violation_severity_instructions", ""),
                criteria=list(cfg.get("violation_severity_criteria", [])),
            ),
        }
        if has_images:
            questions["image_violation_type"] = Choice(
                instructions=cfg.get("image_violation_instructions", ""),
                criteria=cfg.get("image_violation_criteria", {}),
            )
        return questions

    @staticmethod
    def _parse_message_response(resp: Any, *, has_images: bool) -> MessageAssessment:
        inj = resp.nouls["is_prompt_injection"]
        banter = resp.nouls["is_friendly_banter"]
        tv = resp.choices["text_violation_type"]
        vsev = resp.scores["violation_severity"]

        img_type: ImageViolationType = "none"
        img_conf = 0.0
        if has_images and "image_violation_type" in resp.choices:
            iv = resp.choices["image_violation_type"]
            img_type = cast(ImageViolationType, iv.choice)
            img_conf = float(iv.confidence)

        return MessageAssessment(
            status="ok",
            injection_probability=float(inj.noul),
            text_violation=cast(TextViolationType, tv.choice),
            text_confidence=float(tv.confidence),
            image_violation=img_type,
            image_confidence=img_conf,
            banter_probability=float(banter.noul),
            severity=float(vsev.score),
            severity_confidence=float(vsev.confidence),
        )

    async def _query_probability(
        self, instructions: str, state: dict[str, Any]
    ) -> float | None:
        if not self.is_active or self.client is None:
            return None
        try:
            resp = await self.client.system_one(
                state=state,
                questions={"matches": Noul(instructions=instructions)},
                model=self.settings.model,
            )
            value = float(resp.nouls["matches"].noul)
            return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None
        except Exception as exc:
            logger.warning(f"qq_admin Jev probability check failed: {exc}")
            return None

    async def assess_join_request(
        self,
        verify_message: str,
        qa_pairs: list[dict[str, str]],
        *,
        risk_tips: str | None = None,
    ) -> JoinRiskAssessment:
        """Score whether a pending join request looks malicious or promotional."""
        inst = self.catalog.jev.get("join_request", {}).get("is_risky_instructions", "")
        prob = await self._query_probability(
            inst,
            {
                "verify_message": verify_message,
                "qa_pairs": qa_pairs,
                "risk_tips": risk_tips or "",
            },
        )
        if prob is None:
            return JoinRiskAssessment(status="unavailable")
        return JoinRiskAssessment(status="ok", risk_probability=prob)

    async def check_injection(self, text: str) -> SafetyVerdict:
        """Detect prompt-injection attempts against the moderation agent."""
        inst = self.catalog.jev.get("guards", {}).get("input_injection", "")
        prob = await self._query_probability(inst, {"input": text[:2000]})
        if prob is None:
            return SafetyVerdict(blocked=False)
        blocked = prob >= self.settings.injection_block_threshold
        return SafetyVerdict(
            blocked=blocked,
            probability=prob,
            reason="Prompt injection detected." if blocked else "",
        )

    async def verify_action(
        self, *, proposal: dict[str, Any], evidence: dict[str, Any]
    ) -> SafetyVerdict:
        """Second-check whether evidence justifies a proposed write tool call."""
        if not self.settings.enable_action_guardrail or not self.is_active:
            return SafetyVerdict(blocked=False, probability=1.0)
        inst = self.catalog.jev.get("guards", {}).get("moderation_validity", "")
        prob = await self._query_probability(
            inst, {"proposal": proposal, "evidence": evidence}
        )
        if prob is None:
            return SafetyVerdict(
                blocked=True,
                reason="TypeSafe action verification unavailable.",
            )
        blocked = prob < self.settings.action_validity_threshold
        return SafetyVerdict(
            blocked=blocked,
            probability=prob,
            reason="Insufficient evidence for proposed action." if blocked else "",
        )

    async def check_reply(self, text: str) -> SafetyVerdict:
        """Verify that a composed reply is safe and strictly on-topic."""
        inst = self.catalog.jev.get("guards", {}).get("output_safety", "")
        prob = await self._query_probability(inst, {"output": text[:1000]})
        if prob is None:
            return SafetyVerdict(blocked=False)
        blocked = prob >= self.settings.output_safety_threshold
        return SafetyVerdict(
            blocked=blocked,
            probability=prob,
            reason="Unsafe moderation notice blocked." if blocked else "",
        )


__all__ = ["AsyncTypeSafeClient", "JevEvaluator"]
