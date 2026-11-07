import json

from invoice_desk.db import load_case
from invoice_desk.judge import DEFAULT_MODEL, context, model_name
from invoice_desk.rules import run_checks


def test_large_invoices_go_to_the_strong_model_when_one_is_set(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("STRONG_MODEL_NAME", raising=False)
    assert model_name(2_000_000) == DEFAULT_MODEL
    monkeypatch.setenv("STRONG_MODEL_NAME", "strong")
    assert model_name(2_000_000) == "strong"
    assert model_name(100_000) == DEFAULT_MODEL


def test_the_model_sees_the_documents_findings_and_note_but_not_bank_details(conn):
    case = load_case(conn, "INV-007")
    sent = json.loads(context(case, run_checks(case)))
    assert sent["invoice"]["vendor_note"].startswith("Price increase agreed")
    assert sent["purchase_order"][0]["unit_price"] == "£120.00"
    assert sent["findings"] == ["price_variance: DOC-USB is 8.3% above the PO price"]
    assert "bank_account" not in json.dumps(sent)
