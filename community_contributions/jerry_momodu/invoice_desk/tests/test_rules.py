import pytest

from invoice_desk.db import load_case
from invoice_desk.models import Decision, Verdict
from invoice_desk.rules import enforce, run_checks, triage


def codes(conn, invoice_id: str) -> set[str]:
    return {f.code for f in run_checks(load_case(conn, invoice_id))}


@pytest.mark.parametrize(
    ("invoice_id", "expected"),
    [
        ("INV-001", set()),
        ("INV-002", {"over_auto_limit"}),
        ("INV-003", {"duplicate"}),
        ("INV-004", {"vendor_blocked"}),
        ("INV-005", {"bank_mismatch"}),
        ("INV-006", set()),
        ("INV-007", {"price_variance"}),
        ("INV-008", {"qty_over_received", "over_auto_limit"}),
        ("INV-009", {"line_unmatched"}),
        ("INV-010", {"no_po"}),
        ("INV-012", {"over_agent_limit"}),
        ("INV-013", {"arithmetic"}),
        ("INV-015", {"bank_recently_changed", "over_auto_limit"}),
    ],
)
def test_checks_find_what_each_invoice_needs(conn, invoice_id, expected):
    assert codes(conn, invoice_id) == expected


@pytest.mark.parametrize(
    ("invoice_id", "status"),
    [
        ("INV-001", "approved"),
        ("INV-003", "rejected"),
        ("INV-005", "for_review"),
        ("INV-007", None),
        ("INV-010", None),
    ],
)
def test_triage_settles_only_the_clear_cut(conn, invoice_id, status):
    outcome = triage(run_checks(load_case(conn, invoice_id)))
    assert (outcome.status if outcome else None) == status


def verdict(decision: Decision, confidence: float) -> Verdict:
    return Verdict(
        decision=decision, confidence=confidence, reasons="r", policy_sections=[2]
    )


def test_guard_escalates_an_unsure_model():
    outcome = enforce(verdict("approve", 0.6), 100_000)
    assert (outcome.status, outcome.by) == ("for_review", "guard")


def test_guard_escalates_above_the_limit_whatever_the_model_says():
    assert enforce(verdict("approve", 0.99), 3_000_000).status == "for_review"


def test_guard_keeps_a_confident_verdict():
    outcome = enforce(verdict("reject", 0.9), 100_000)
    assert (outcome.status, outcome.by) == ("rejected", "model")
