"""TypeSafe AI Jev safety classifier with fixed questions and SafetyReport output."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from typesafe_sdk import AsyncTypeSafeClient, Content, Image, Noul, Score

from qq_admin.config import Config
from qq_admin.prompts import PromptCatalog

_IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}

CRITICAL_FIELDS: tuple[str, ...] = (
    "violence",
    "sexual_content",
    "suicide_self_harm",
    "political_sensitive",
)
ATTACK_FIELDS: tuple[str, ...] = (
    "jailbreak",
    "prompt_injection",
)
ORDER_FIELDS: tuple[str, ...] = (
    "non_violent_crime",
    "pii",
    "unethical_behavior",
    "copyright_infringement",
    "advertising",
)
SAFETY_FIELDS: tuple[str, ...] = CRITICAL_FIELDS + ATTACK_FIELDS + ORDER_FIELDS

_AD_FIELDS = {"advertising", "copyright_infringement", "non_violent_crime"}
_ABUSE_FIELDS = set(CRITICAL_FIELDS) | {"pii", "unethical_behavior"}


class SafetyReport(BaseModel):
    """Structured safety scores returned by Jev.execute()."""

    violence: float = 0.0
    sexual_content: float = 0.0
    suicide_self_harm: float = 0.0
    political_sensitive: float = 0.0
    jailbreak: float = 0.0
    non_violent_crime: float = 0.0
    pii: float = 0.0
    unethical_behavior: float = 0.0
    copyright_infringement: float = 0.0
    advertising: float = 0.0
    prompt_injection: float = 0.0
    severity: int = 0

    def scores(self, fields: Sequence[str] | None = None) -> dict[str, float]:
        names = fields if fields is not None else SAFETY_FIELDS
        return {
            name: float(getattr(self, name)) for name in names if name in SAFETY_FIELDS
        }

    def triggered(
        self, threshold: float = 0.70, fields: Sequence[str] | None = None
    ) -> list[str]:
        return [
            name for name, score in self.scores(fields).items() if score >= threshold
        ]

    @property
    def primary_category(self) -> str:
        top_name, top_score = max(self.scores().items(), key=lambda kv: kv[1])
        return top_name if top_score > 0.0 else "none"

    @property
    def max_risk(self) -> float:
        return max(self.scores().values())

    @property
    def max_attack_risk(self) -> float:
        return max(self.jailbreak, self.prompt_injection)

    @property
    def warning_category(self) -> Literal["spam", "abuse", "ad"]:
        top = self.primary_category
        if top in _AD_FIELDS:
            return "ad"
        if top in _ABUSE_FIELDS:
            return "abuse"
        return "spam"

    def is_flagged(self, threshold: float = 0.70) -> bool:
        return self.severity > 0 and self.max_risk >= threshold

    def summary(self, threshold: float = 0.70) -> str:
        hits = self.triggered(threshold)
        return (
            f"categories={hits or ['none']}, severity={self.severity}, "
            f"max_risk={self.max_risk:.2f}, attack={self.max_attack_risk:.2f}"
        )


class Jev:
    """Stateless Jev classifier accepting text, images, text+images, or links."""

    def __init__(
        self,
        config: Config,
        catalog: PromptCatalog,
        *,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        self.config = config
        self._catalog = catalog
        self._client = client
        self._owns_client = client is None
        self._category_questions: dict[str, Noul] = {
            name: Noul(instructions=inst)
            for name, inst in catalog.jev_questions().items()
        }
        self._severity_question = Score(
            instructions=catalog.jev_severity_instructions(),
            criteria=catalog.jev_severity_criteria(),
        )

    @property
    def is_ready(self) -> bool:
        return self._client is not None or bool(self.config.jev_api_key.strip())

    def _get_client(self) -> AsyncTypeSafeClient:
        if self._client is None:
            self._client = AsyncTypeSafeClient(
                api_key=self.config.jev_api_key.strip(),
                model=self.config.jev_model,
                timeout=self.config.timeout_seconds,
                headers=_IMAGE_HEADERS,
            )
            self._owns_client = True
        return self._client

    def _select_questions(
        self,
        *,
        categories: Sequence[str] | None,
        has_text_or_urls: bool,
        include_severity: bool,
    ) -> dict[str, Noul | Score]:
        wanted = set(categories) if categories is not None else set(SAFETY_FIELDS)
        if not has_text_or_urls:
            wanted -= set(ATTACK_FIELDS)
        questions: dict[str, Noul | Score] = {
            name: q for name, q in self._category_questions.items() if name in wanted
        }
        if include_severity and questions:
            questions["severity"] = self._severity_question
        return questions

    async def execute(
        self,
        *,
        text: str = "",
        images: Sequence[bytes | Path] | None = None,
        urls: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        include_severity: bool = True,
    ) -> SafetyReport:
        """Classify text, images, text+images, or links into a SafetyReport."""
        if not self.is_ready:
            return SafetyReport()

        clean_text = text.strip()[:2000]
        clean_urls = [u.strip() for u in (urls or []) if u and u.strip()]
        assets = {f"img_{i}": Image(raw) for i, raw in enumerate(images or [], start=1)}
        if not clean_text and not clean_urls and not assets:
            return SafetyReport()

        questions = self._select_questions(
            categories=categories,
            has_text_or_urls=bool(clean_text or clean_urls),
            include_severity=include_severity,
        )
        if not questions:
            return SafetyReport()

        state: dict[str, Any] = {}
        if clean_text:
            state["text"] = clean_text
        if clean_urls:
            state["urls"] = clean_urls
        if assets:
            state["images"] = list(assets)

        resp = await self._get_client().system_one(
            state=state,
            questions=questions,
            model=self.config.jev_model,
            assets=assets or None,
        )

        values: dict[str, Any] = {
            name: float(resp.nouls[name].noul)
            for name in SAFETY_FIELDS
            if name in resp.nouls
        }
        if "severity" in resp.scores:
            values["severity"] = round(float(resp.scores["severity"].score))
        return SafetyReport.model_validate(values)

    async def probability(self, state: Content, instructions: str) -> float:
        """Run a single Noul check for join-request review or optional tool judge."""
        resp = await self._get_client().system_one(
            state=state,
            questions={"answer": Noul(instructions=instructions)},
            model=self.config.jev_model,
        )
        return float(resp.nouls["answer"].noul)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "ATTACK_FIELDS",
    "CRITICAL_FIELDS",
    "ORDER_FIELDS",
    "SAFETY_FIELDS",
    "AsyncTypeSafeClient",
    "Jev",
    "SafetyReport",
]
