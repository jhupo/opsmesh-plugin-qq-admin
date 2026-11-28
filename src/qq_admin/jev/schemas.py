"""Structured result schemas for TypeSafe AI Jev assessments."""

from typing import Literal

from pydantic import BaseModel, Field

from qq_admin.config import JevSettings

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


class MessageAssessment(BaseModel):
    """Calibrated multimodal message assessment returned by TypeSafe Jev."""

    status: Literal["ok", "unavailable"] = "ok"
    injection_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    text_violation: TextViolationType = "none"
    text_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    image_violation: ImageViolationType = "none"
    image_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    banter_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: float = Field(default=0.0, ge=0.0, le=4.0)
    severity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def has_violation(self) -> bool:
        return self.text_violation != "none" or self.image_violation != "none"

    @property
    def primary_violation(self) -> str:
        if self.image_violation != "none" and (
            self.image_confidence >= self.text_confidence
            or self.text_violation == "none"
        ):
            return f"image:{self.image_violation}"
        if self.text_violation != "none":
            return f"text:{self.text_violation}"
        return "none"

    @property
    def warning_category(self) -> Literal["spam", "abuse", "ad"]:
        if self.image_violation == "qr_ad_promo" or self.text_violation in (
            "commercial_ad",
            "scam_phishing",
        ):
            return "ad"
        if self.text_violation == "spam_flood" or (
            self.image_violation == "spam_meme_flood"
        ):
            return "spam"
        return "abuse"

    @property
    def effective_confidence(self) -> float:
        type_conf = max(
            self.text_confidence if self.text_violation != "none" else 0.0,
            self.image_confidence if self.image_violation != "none" else 0.0,
        )
        return min(type_conf, self.severity_confidence)

    def enforcement_tier(
        self, settings: JevSettings
    ) -> Literal["none", "warn", "enforce", "severe"]:
        """Map calibrated severity and confidence to an enforcement tier."""
        if (
            self.status != "ok"
            or self.injection_probability >= settings.injection_block_threshold
            or not self.has_violation
            or self.severity < 1.0
        ):
            return "none"
        if (
            self.banter_probability >= 0.75
            and self.text_violation in ("harassment_abuse", "flame_bait")
            and self.image_violation == "none"
        ):
            return "none"

        conf = self.effective_confidence
        if self.severity >= 3.2 and conf >= settings.enforce_confidence:
            return "severe"
        if self.severity >= 2.0 and conf >= settings.enforce_confidence:
            return "enforce"
        if self.severity >= 1.0 and conf >= settings.warn_confidence:
            return "warn"
        return "none"


class JoinRiskAssessment(BaseModel):
    """Calibrated spam/abuse risk score for a group join request."""

    status: Literal["ok", "unavailable"] = "ok"
    risk_probability: float = Field(default=0.0, ge=0.0, le=1.0)


class SafetyVerdict(BaseModel):
    """Binary guardrail decision backed by a calibrated TypeSafe Noul score."""

    blocked: bool
    probability: float = 0.0
    reason: str = ""


__all__ = [
    "ImageViolationType",
    "JoinRiskAssessment",
    "MessageAssessment",
    "SafetyVerdict",
    "TextViolationType",
]
