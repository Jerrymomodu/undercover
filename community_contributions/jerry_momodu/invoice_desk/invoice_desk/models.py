"""The shapes passed between the checks, the model and the pipeline."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["block", "review", "flag"]
Status = Literal["approved", "rejected", "for_review"]
Decision = Literal["approve", "reject", "escalate"]


@dataclass(frozen=True)
class Case:
    """One invoice with everything needed to check it."""

    invoice: dict[str, Any]
    vendor: dict[str, Any] | None
    po: dict[str, Any] | None
    receipt: dict[str, Any] | None
    duplicate_of: str | None


@dataclass(frozen=True)
class Finding:
    """A check's result: block rejects, review escalates, flag needs judgement."""

    code: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class Outcome:
    """Where an invoice ends up, who put it there and why."""

    status: Status
    by: str
    reason: str


class Verdict(BaseModel):
    """The model's judgement on one invoice."""

    decision: Decision
    confidence: float = Field(
        ge=0, le=1, description="How sure you are this is what the policy requires"
    )
    reasons: str = Field(description="One or two sentences a person can check")
    policy_sections: list[int] = Field(description="The policy sections you relied on")
