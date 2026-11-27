"""Execution contexts and normalized outcomes shared by commands and public APIs."""

from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field
from qq import Gateway

from .typing import AuditSource, RoleTier


class OperatorIdentity(BaseModel):
    """Caller identity and normalized authority tier."""

    model_config = ConfigDict(extra="ignore")

    openid: str
    role: RoleTier = RoleTier.MEMBER
    is_superuser: bool = False

    @property
    def effective_role(self) -> RoleTier:
        return RoleTier.SUPERUSER if self.is_superuser else self.role


class AdminContext(BaseModel):
    """Runtime execution context passed into ModerationService and public APIs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    gateway: Gateway
    group_openid: str
    operator: OperatorIdentity
    source: AuditSource = AuditSource.API
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])


class ModerationOutcome(BaseModel):
    """Standardized return structure produced by ModerationService and public APIs."""

    action: str
    group_openid: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


__all__ = ["AdminContext", "ModerationOutcome", "OperatorIdentity"]
