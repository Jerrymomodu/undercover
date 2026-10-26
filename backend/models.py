"""The shapes of the UnderCover API."""

from typing import Literal

from pydantic import BaseModel

Status = Literal["waiting", "in_progress", "awaiting_sign_off", "decided"]


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


class Claim(BaseModel):
    claim_id: str
    status: Status
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
