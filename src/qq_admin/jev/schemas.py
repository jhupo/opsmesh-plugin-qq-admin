"""Structured result schemas for System 1 TypeSafe AI Jev evaluations."""

from typing import Literal

from pydantic import BaseModel, Field

from qq_admin.config import JevConfig

TextViolationType = Literal[
    "none",
    "spam_flood",
    "commercial_ad",
    "harassment_abuse",
    "flame_bait",
    "scam_phishing",
    "nsfw_illegal",
    "doxxing_privacy",
]

ImageViolationType = Literal[
    "none",
    "qr_ad_promo",
    "nsfw_gore",
    "scam_screenshot",
    "spam_meme_flood",
]


class MessageEvaluation(BaseModel):
    """Calibrated multimodal moderation assessment returned by TypeSafe Jev."""

    status: Literal["ok", "unavailable"] = "ok"
    is_prompt_injection_prob: float = Field(default=0.0, ge=0.0, le=1.0)
    text_violation_type: TextViolationType = "none"
    text_violation_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    image_violation_type: ImageViolationType = "none"
    image_violation_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_friendly_banter_prob: float = Field(default=0.0, ge=0.0, le=1.0)
    violation_severity: float = Field(default=0.0, ge=0.0, le=4.0)
    severity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def has_violation(self) -> bool:
        return self.text_violation_type != "none" or self.image_violation_type != "none"

    @property
    def primary_violation(self) -> str:
        if self.image_violation_type != "none" and (
            self.image_violation_confidence >= self.text_violation_confidence
            or self.text_violation_type == "none"
        ):
            return f"image:{self.image_violation_type}"
        if self.text_violation_type != "none":
            return f"text:{self.text_violation_type}"
        return "none"

    @property
    def warning_category(self) -> Literal["spam", "abuse", "ad"]:
        if self.image_violation_type == "qr_ad_promo" or self.text_violation_type in (
            "commercial_ad",
            "scam_phishing",
        ):
            return "ad"
        if self.text_violation_type == "spam_flood" or (
            self.image_violation_type == "spam_meme_flood"
        ):
            return "spam"
        return "abuse"

    @property
    def effective_confidence(self) -> float:
        type_conf = max(
            self.text_violation_confidence
            if self.text_violation_type != "none"
            else 0.0,
            self.image_violation_confidence
            if self.image_violation_type != "none"
            else 0.0,
        )
        return min(type_conf, self.severity_confidence)

    def moderation_tier(
        self, cfg: JevConfig
    ) -> Literal["none", "warn", "auto_enforce", "severe"]:
        """Derive enforcement tier from calibrated severity and confidence."""
        if (
            self.status != "ok"
            or self.is_prompt_injection_prob >= cfg.injection_block_threshold
            or not self.has_violation
            or self.violation_severity < 1.0
        ):
            return "none"
        if (
            self.is_friendly_banter_prob >= 0.75
            and self.text_violation_type in ("harassment_abuse", "flame_bait")
            and self.image_violation_type == "none"
        ):
            return "none"

        conf = self.effective_confidence
        if self.violation_severity >= 3.2 and conf >= cfg.auto_enforce_confidence:
            return "severe"
        if self.violation_severity >= 2.0 and conf >= cfg.auto_enforce_confidence:
            return "auto_enforce"
        if self.violation_severity >= 1.0 and conf >= cfg.warn_confidence:
            return "warn"
        return "none"


class JoinRiskEvaluation(BaseModel):
    """Calibrated risk score for an inbound group join request."""

    status: Literal["ok", "unavailable"] = "ok"
    risk_probability: float = Field(default=0.0, ge=0.0, le=1.0)


class GuardVerdict(BaseModel):
    """Binary guardrail decision backed by a calibrated TypeSafe Noul score."""

    blocked: bool
    probability: float = 0.0
    reason: str = ""


__all__ = [
    "GuardVerdict",
    "ImageViolationType",
    "JoinRiskEvaluation",
    "MessageEvaluation",
    "TextViolationType",
]
