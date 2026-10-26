"""The shapes of the UnderCover API."""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

Status = Literal["waiting", "in_progress", "awaiting_sign_off", "decided"]
Outcome = Literal["approve", "decline", "refer"]
StepKind = Literal["tool_call", "tool_result", "reply", "note"]


class Decision(BaseModel):
    decision: Outcome
    payout: float
    reason: str
    policy_section: str
    decided_at: str


class SignOff(BaseModel):
    handler_id: str
    handler_name: str
    signed_off_at: str


class Payment(BaseModel):
    amount: float
    paid_at: str


class ClaimState(BaseModel):
    claim_id: str
    status: Status
    decision: Decision | None
    sign_off: SignOff | None
    payment: Payment | None


class StartRequest(BaseModel):
    thread_id: str = Field(min_length=1)


class StepRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    kind: StepKind
    text: str = Field(min_length=1)


class Step(BaseModel):
    step_id: int
    thread_id: str
    kind: StepKind
    text: str
    created_at: str


class DecisionRequest(BaseModel):
    decision: Outcome
    payout: float = Field(ge=0, description="In US dollars; zero unless approved.")
    reason: str = Field(min_length=1)
    policy_section: str = Field(min_length=1)

    @field_validator("payout")
    @classmethod
    def to_cents(cls, payout: float) -> float:
        return round(payout, 2)

    @model_validator(mode="after")
    def payout_matches_decision(self) -> Self:
        if self.decision == "approve" and self.payout == 0:
            raise ValueError("An approval needs a payout over zero.")
        if self.decision != "approve" and self.payout != 0:
            raise ValueError("A decline or a referral pays nothing.")
        return self


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0, description="In US dollars.")


class SignOffRequest(BaseModel):
    handler_id: str


class RunStarted(BaseModel):
    thread_id: str


class Item(BaseModel):
    description: str
    category: str
    amount: float


class ClaimDocument(BaseModel):
    name: str
    type: str
    content: str


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    claim_type: str
    amount_claimed: float
    submitted_on: str
    status: Status
    decision: Outcome | None
    payout: float | None


class Claim(ClaimState):
    policy_id: str
    customer_id: str
    claim_type: str
    submitted_on: str
    incident_date: str
    incident_location: str
    summary: str
    story: str
    items: list[Item]
    amount_claimed: float
    documents: list[ClaimDocument]


class Plan(BaseModel):
    plan: str
    name: str
    trip_cancellation_max: float
    trip_delay_waiting_hours: int
    trip_delay_max: float
    baggage_delay_waiting_hours: int
    baggage_delay_max: float
    baggage_max: float
    per_item_limit: float
    passport_max: float
    emergency_medical_max: float
    deductible: float


class AddOn(BaseModel):
    add_on: str
    name: str
    effect: str
    electronics_per_item_limit: float | None


class Trip(BaseModel):
    destination: str
    departs_on: str
    returns_on: str
    trip_cost: float


class Policy(BaseModel):
    policy_id: str
    customer_id: str
    plan: Plan
    add_ons: list[AddOn]
    purchased_on: str
    sold_through: str
    trip: Trip
    travelers: list[str]
    status: str


class PreviousClaim(BaseModel):
    claim_id: str
    filed_on: str
    incident_date: str
    claim_type: str
    summary: str
    outcome: str
    amount_paid: float


class ClaimHistory(BaseModel):
    customer_id: str
    previous_claims: list[PreviousClaim]


class Address(BaseModel):
    street: str
    city: str
    state: str
    zip: str


class Customer(ClaimHistory):
    name: str
    email: str
    phone: str
    date_of_birth: str
    address: Address
    customer_since: str


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    email: str
    can_approve_over_limit: bool


class Text(BaseModel):
    content: str
