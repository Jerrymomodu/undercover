"""Rebuild the UnderCover database from data/."""

import json
from contextlib import closing
from typing import Any

from backend import db

DATA = db.ROOT / "data"


def load(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def with_json(record: dict[str, Any], *fields: str) -> dict[str, Any]:
    """Return the record with the named fields stored as JSON text."""
    return record | {field: json.dumps(record[field]) for field in fields}


def seed() -> None:
    """Drop every table and load the business data again."""
    plans = load("plans.json")
    with closing(db.connect()) as connection:
        connection.executescript(db.SCHEMA)
        with connection:
            connection.executemany(
                "INSERT INTO settings VALUES (?, ?)",
                [(k, json.dumps(v)) for k, v in load("company.json").items()],
            )
            connection.execute(
                "INSERT INTO documents VALUES ('policy_wording', ?)",
                ((DATA / "policy_wording.md").read_text(encoding="utf-8"),),
            )
            connection.executemany(
                """INSERT INTO plans VALUES (:plan, :name, :trip_cancellation_max,
                :trip_delay_waiting_hours, :trip_delay_max,
                :baggage_delay_waiting_hours, :baggage_delay_max, :baggage_max,
                :per_item_limit, :passport_max, :emergency_medical_max, :deductible)""",
                plans["plans"],
            )
            connection.executemany(
                """INSERT INTO add_ons
                VALUES (:add_on, :name, :effect, :electronics_per_item_limit)""",
                [{"electronics_per_item_limit": None} | a for a in plans["add_ons"]],
            )
            connection.executemany(
                """INSERT INTO handlers
                VALUES (:handler_id, :name, :role, :email, :can_approve_over_limit)""",
                load("handlers.json"),
            )
            connection.executemany(
                """INSERT INTO customers VALUES (:customer_id, :name, :email, :phone,
                :date_of_birth, :address, :customer_since, :previous_claims)""",
                [
                    with_json(c, "address", "previous_claims")
                    for c in load("customers.json")
                ],
            )
            connection.executemany(
                """INSERT INTO policies VALUES (:policy_id, :customer_id, :plan,
                :add_ons, :purchased_on, :sold_through, :trip, :travelers, :status)""",
                [
                    with_json(p, "add_ons", "trip", "travelers")
                    for p in load("policies.json")
                ],
            )
            connection.executemany(
                """INSERT INTO claims VALUES (:claim_id, :policy_id, :customer_id,
                :claim_type, :submitted_on, :incident_date, :incident_location,
                :summary, :story, :items, :amount_claimed, :documents, 'waiting')""",
                [with_json(c, "items", "documents") for c in load("claims.json")],
            )


if __name__ == "__main__":
    seed()
    print(f"Seeded {db.path()}")
